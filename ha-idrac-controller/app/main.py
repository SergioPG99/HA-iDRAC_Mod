# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys
import signal
import threading
import re
import json 

from . import ipmi_manager
from . import web_server
from . import mqtt_client

# --- Global Variables ---
running = True
addon_options = {}
server_info = {
    "manufacturer": "Unknown", "model": "Unknown", "is_gen14_plus": False,
    "cpu_generic_temp_pattern": None, 
    "inlet_temp_name_pattern": None, 
    "exhaust_temp_name_pattern": None
}
app_config = {} 
loop_count = 0
current_parsed_status = { # For sharing with web_server via file
    "cpu_temps_c": [], "hottest_cpu_temp_c": "N/A",
    "inlet_temp_c": "N/A", "exhaust_temp_c": "N/A",
    "target_fan_speed_percent": "N/A", "actual_fan_rpms": [],
    "last_updated": "Never"
}
STATUS_FILE = "/data/current_status.json"

# MQTT Discovery Tracking
# Use sets to store unique identifiers (slugs) of sensors for which discovery has been published
discovered_cpu_sensors = set()
discovered_fan_rpm_sensors = set()
static_sensors_discovered = False # For Inlet, Exhaust, Target Fan Speed

# --- Graceful Shutdown & Helpers ---
def graceful_shutdown(signum, frame):
    global running
    print("[MAIN] Shutdown signal received. Cleaning up...", flush=True)
    running = False

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

def determine_server_generation(model_name):
    if not model_name: return False
    match = re.search(r"^[RT]\s?(\d)(\d)\d+", model_name.upper())
    if match:
        try:
            gen_indicator_digit = int(match.group(2))
            if gen_indicator_digit >= 4: return True
        except (IndexError, ValueError): pass
    return False

def celsius_to_fahrenheit(celsius):
    if celsius is None: return None
    return round((celsius * 9/5) + 32, 1)

def fahrenheit_to_celsius(fahrenheit):
    if fahrenheit is None: return None
    return round((fahrenheit - 32) * 5/9, 1)

def validate_and_convert_fan_curve(fan_curve, temp_unit, log_level):
    """Validate fan curve structure and convert temperatures to Celsius if needed."""
    if not fan_curve or len(fan_curve) < 2:
        return None, "Fan curve requires at least 2 points"
    
    validated_curve = []
    for i, point in enumerate(fan_curve):
        # Validate required keys
        if not isinstance(point, dict):
            return None, f"Fan curve point {i} must be a dictionary"
        if 'temp' not in point or 'speed' not in point:
            return None, f"Fan curve point {i} missing 'temp' or 'speed' key"
        
        try:
            temp = float(point['temp'])
            speed = int(point['speed'])
        except (ValueError, TypeError):
            return None, f"Fan curve point {i} has invalid temp or speed value"
        
        # Validate that temp is not None and is a valid number
        if temp is None or temp < -273:  # Below absolute zero is invalid
            return None, f"Fan curve point {i} has invalid temperature value"
        
        # Validate ranges
        if speed < 0 or speed > 100:
            return None, f"Fan curve point {i} speed must be 0-100%, got {speed}%"
        
        # Convert temperature if needed
        if temp_unit == "F":
            temp_c = fahrenheit_to_celsius(temp)
            if temp_c is None:
                return None, f"Fan curve point {i} temperature conversion failed"
            temp = temp_c
        
        validated_curve.append({'temp': temp, 'speed': speed})
    
    # Sort by temperature
    validated_curve.sort(key=lambda p: p['temp'])
    
    print(f"[{log_level.upper()}] Validated fan curve with {len(validated_curve)} points", flush=True)
    return validated_curve, None

def save_current_status_to_file(status_dict):
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(status_dict, f, indent=4)
    except (IOError, PermissionError) as e:
        print(f"[ERROR] Could not save status to {STATUS_FILE}: {e}", flush=True)

# --- Main Application Logic ---
def load_and_configure(mqtt_handler): # Pass mqtt_handler to set device_info
    global addon_options, app_config, server_info
    print("[MAIN] Loading configuration and initializing...", flush=True)
    
    addon_options = {
        "idrac_ip": os.getenv("IDRAC_IP"), "idrac_username": os.getenv("IDRAC_USERNAME"),
        "idrac_password": os.getenv("IDRAC_PASSWORD"),
        "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),
        "log_level": os.getenv("LOG_LEVEL", "info").lower(),
        "fan_control_enabled": os.getenv("FAN_CONTROL_ENABLED", "true").lower() == "true",
        "fan_control_mode": os.getenv("FAN_CONTROL_MODE", "simple").lower(),
        "temperature_unit": os.getenv("TEMPERATURE_UNIT", "C").upper(),
        "base_fan_speed_percent": int(os.getenv("BASE_FAN_SPEED_PERCENT", "20")),
        "low_temp_threshold": int(os.getenv("LOW_TEMP_THRESHOLD", "45")),
        "high_temp_fan_speed_percent": int(os.getenv("HIGH_TEMP_FAN_SPEED_PERCENT", "50")),
        "critical_temp_threshold": int(os.getenv("CRITICAL_TEMP_THRESHOLD", "65")),
        "mqtt_host": os.getenv("MQTT_HOST", "core-mosquitto"),
        "mqtt_port": int(os.getenv("MQTT_PORT", "1883")),
        "mqtt_username": os.getenv("MQTT_USERNAME", ""),
        "mqtt_password": os.getenv("MQTT_PASSWORD", "")
    }
    
    # Load fan curve if provided
    fan_curve_env = os.getenv("FAN_CURVE", "[]")
    try:
        addon_options["fan_curve"] = json.loads(fan_curve_env)
    except json.JSONDecodeError:
        addon_options["fan_curve"] = []
    log_level = addon_options['log_level']
    print(f"[{log_level.upper()}] Add-on options loaded: IDRAC_IP={addon_options['idrac_ip']}, LogLevel={log_level}", flush=True)

    ipmi_manager.configure_ipmi(
        addon_options["idrac_ip"], addon_options["idrac_username"], 
        addon_options["idrac_password"], log_level=log_level
    )

    model_data = ipmi_manager.get_server_model_info()
    if model_data and model_data.get("model") != "Unknown":
        server_info.update(model_data)
        server_info["is_gen14_plus"] = determine_server_generation(server_info["model"])
        print(f"[{log_level.upper()}] Server: {server_info['manufacturer']} {server_info['model']} (Gen14+: {server_info['is_gen14_plus']})", flush=True)
    else:
        print(f"[WARNING] Could not determine server model.", flush=True)
    
    if mqtt_handler: # Configure MQTT client with device info
        mqtt_handler.configure_broker(
            addon_options["mqtt_host"], addon_options["mqtt_port"],
            addon_options["mqtt_username"], addon_options["mqtt_password"],
            log_level
        )
        mqtt_handler.set_device_info(
            server_info.get("manufacturer"), 
            server_info.get("model"), 
            addon_options.get("idrac_ip")
        )

    server_info["cpu_generic_temp_pattern"] = r"^Temp$" 
    server_info["inlet_temp_name_pattern"] = r"Inlet Temp"
    server_info["exhaust_temp_name_pattern"] = r"Exhaust Temp"
    print(f"[{log_level.upper()}] Using temp patterns: CPU_generic='{server_info['cpu_generic_temp_pattern']}', Inlet='{server_info['inlet_temp_name_pattern']}', Exhaust='{server_info['exhaust_temp_name_pattern']}'", flush=True)

    app_config = web_server.load_app_config()
    print(f"[{log_level.upper()}] Loaded app config: {app_config}", flush=True)

    temp_unit = addon_options["temperature_unit"]
    if temp_unit == "F":
        addon_options["low_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["low_temp_threshold"])
        addon_options["critical_temp_threshold_c"] = fahrenheit_to_celsius(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (F input converted to C): Low={addon_options['low_temp_threshold_c']:.1f}C, Critical={addon_options['critical_temp_threshold_c']:.1f}C", flush=True)
    else:
        addon_options["low_temp_threshold_c"] = float(addon_options["low_temp_threshold"])
        addon_options["critical_temp_threshold_c"] = float(addon_options["critical_temp_threshold"])
        print(f"[{log_level.upper()}] Temp thresholds (C input): Low={addon_options['low_temp_threshold_c']}C, Critical={addon_options['critical_temp_threshold_c']}C", flush=True)

    # Validate and convert fan curve if using curve mode
    if addon_options["fan_control_mode"] == "curve":
        validated_curve, error = validate_and_convert_fan_curve(
            addon_options.get("fan_curve", []), 
            temp_unit, 
            log_level
        )
        if error:
            print(f"[WARNING] Fan curve validation failed: {error}. Falling back to simple mode.", flush=True)
            addon_options["fan_control_mode"] = "simple"
        else:
            addon_options["fan_curve"] = validated_curve


def main_control_loop(mqtt_handler):
    global running, app_config, addon_options, server_info, loop_count, current_parsed_status
    global discovered_cpu_sensors, discovered_fan_rpm_sensors # static_sensors_discovered is managed by mqtt_client on_connect
    
    log_level = addon_options['log_level']

    if not (addon_options["idrac_ip"] and addon_options["idrac_username"] and addon_options["idrac_password"]):
        print("[ERROR] iDRAC credentials not fully configured. Exiting.", flush=True)
        return 
    
    print(f"[{log_level.upper()}] Entering main control loop. Interval: {addon_options['check_interval_seconds']}s", flush=True)

    while running:
        start_time = time.time()
        # Initialize sleep_duration at the start of the loop to a default
        # This ensures it's always defined before the end-of-loop sleep logic.
        sleep_duration = float(addon_options["check_interval_seconds"])


        try: # Add a try block for the main work of the cycle
            print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} Start ---", flush=True)

            if loop_count > 0 and loop_count % 5 == 0: # Reload app_config periodically
                print(f"[{log_level.upper()}] Reloading app config from /data/app_config.json", flush=True)
                app_config = web_server.load_app_config()

            # --- Retrieve and Parse Temperatures ---
            raw_temp_sdr_data = ipmi_manager.retrieve_temperatures_raw()
            parsed_temperatures_c = {"cpu_temps": [], "inlet_temp": None, "exhaust_temp": None}
            if raw_temp_sdr_data:
                if log_level in ["trace", "debug"]:
                    print(f"[{log_level.upper()}] RAW TEMP SDR DATA:\n{raw_temp_sdr_data}\n-------------------------", flush=True)
                parsed_temperatures_c = ipmi_manager.parse_temperatures(
                    raw_temp_sdr_data, server_info["cpu_generic_temp_pattern"],
                    server_info["inlet_temp_name_pattern"], server_info["exhaust_temp_name_pattern"]
                )
                print(f"[{log_level.upper()}] Parsed Temperatures (C): {parsed_temperatures_c}", flush=True)
            else:
                print(f"[WARNING] Failed to retrieve temp SDR data.", flush=True)

            # --- Retrieve and Parse Fan RPMs ---
            raw_fan_sdr_data = ipmi_manager.retrieve_fan_rpms_raw()
            parsed_fan_rpms = []
            if raw_fan_sdr_data:
                if log_level in ["trace", "debug"]:
                    print(f"[{log_level.upper()}] RAW FAN SDR DATA:\n{raw_fan_sdr_data}\n-------------------------", flush=True)
                parsed_fan_rpms = ipmi_manager.parse_fan_rpms(raw_fan_sdr_data)
                print(f"[{log_level.upper()}] Parsed Fan RPMs: {parsed_fan_rpms}", flush=True)
            else:
                print(f"[WARNING] Failed to retrieve fan SDR data.", flush=True)

            # --- Retrieve and Parse Power Consumption ---
            raw_power_sdr_data = ipmi_manager.retrieve_power_sdr_raw()
            power_consumption_watts = None
            if raw_power_sdr_data:
                if log_level in ["trace", "debug"]:
                    print(f"[{log_level.upper()}] RAW POWER SDR DATA:\n{raw_power_sdr_data}\n-------------------------", flush=True)
                power_consumption_watts = ipmi_manager.parse_power_consumption(raw_power_sdr_data)
                print(f"[{log_level.upper()}] Parsed Power Consumption: {power_consumption_watts}W", flush=True)
            else:
                print(f"[WARNING] Failed to retrieve power SDR data.", flush=True)

            # --- Dynamic MQTT Discovery (CPUs and Fans) ---
            if mqtt_handler and mqtt_handler.is_connected:
                cpu_temps_list_c_current_cycle = parsed_temperatures_c.get("cpu_temps", [])
                if len(discovered_cpu_sensors) != len(cpu_temps_list_c_current_cycle) or not discovered_cpu_sensors : # Discover if count changed or never discovered
                    print(f"[{log_level.upper()}] CPU count is {len(cpu_temps_list_c_current_cycle)}. Discovering CPUs.", flush=True)
                    new_cpu_slugs = set()
                    for i in range(len(cpu_temps_list_c_current_cycle)):
                        slug = f"cpu_{i}_temp"
                        mqtt_handler.publish_sensor_discovery(
                            sensor_type_slug=slug, sensor_name=f"CPU {i} Temperature",
                            device_class="temperature", unit_of_measurement="°C",
                            value_template="{{ value_json.temperature | round(1) }}"
                        )
                        new_cpu_slugs.add(slug)
                    discovered_cpu_sensors = new_cpu_slugs
                
                for i, fan_info in enumerate(parsed_fan_rpms):
                    fan_name = fan_info["name"]
                    safe_fan_name_slug = re.sub(r'[^a-zA-Z0-9_]+', '_', fan_name).lower().strip('_')
                    if not safe_fan_name_slug: safe_fan_name_slug = f"fan_{i}"
                    rpm_sensor_slug = f"fan_{safe_fan_name_slug}_rpm"
                    if rpm_sensor_slug not in discovered_fan_rpm_sensors:
                        mqtt_handler.publish_sensor_discovery(
                            sensor_type_slug=rpm_sensor_slug, sensor_name=f"{fan_name} RPM",
                            unit_of_measurement="RPM", icon="mdi:fan",
                            value_template="{{ value_json.rpm | round(0) }}"
                        )
                        discovered_fan_rpm_sensors.add(rpm_sensor_slug)

            # --- Determine Hottest CPU ---
            hottest_cpu_temp_c = None
            cpu_temps_list_c = parsed_temperatures_c.get("cpu_temps", [])
            if cpu_temps_list_c:
                hottest_cpu_temp_c = max(cpu_temps_list_c)
                print(f"[{log_level.upper()}] Hottest CPU Temp: {hottest_cpu_temp_c}°C from {cpu_temps_list_c}", flush=True)
            else:
                print(f"[WARNING] No CPU temperatures available for fan control.", flush=True)

            # --- Fan Control Logic ---
            target_fan_speed_display = "N/A" 
            if addon_options["fan_control_enabled"]:
                if hottest_cpu_temp_c is not None:
                    crit_thresh_c = addon_options["critical_temp_threshold_c"]
                    
                    # Check critical temperature first (applies to both modes)
                    if hottest_cpu_temp_c >= crit_thresh_c:
                        print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) >= CRITICAL ({crit_thresh_c}°C). Dell auto.", flush=True)
                        ipmi_manager.apply_dell_fan_control_profile()
                        target_fan_speed_display = "Dell Auto"
                    elif addon_options["fan_control_mode"] == "curve":
                        # Curve mode: Multi-point interpolation (curve already validated and converted)
                        fan_curve = addon_options.get("fan_curve", [])
                        if fan_curve and len(fan_curve) >= 2:
                            # Handle edge cases first
                            if hottest_cpu_temp_c <= fan_curve[0]['temp']:
                                # Below or at lowest point
                                target_fan_speed_val = fan_curve[0]['speed']
                            elif hottest_cpu_temp_c >= fan_curve[-1]['temp']:
                                # At or above highest point
                                target_fan_speed_val = fan_curve[-1]['speed']
                            else:
                                # Find the two points to interpolate between
                                lower_point = fan_curve[0]
                                upper_point = fan_curve[1]
                                
                                for i in range(len(fan_curve) - 1):
                                    if fan_curve[i]['temp'] <= hottest_cpu_temp_c < fan_curve[i+1]['temp']:
                                        lower_point = fan_curve[i]
                                        upper_point = fan_curve[i+1]
                                        break
                                
                                # Linear interpolation
                                temp_range = upper_point['temp'] - lower_point['temp']
                                speed_range = upper_point['speed'] - lower_point['speed']
                                if temp_range > 0:
                                    target_fan_speed_val = lower_point['speed'] + ((hottest_cpu_temp_c - lower_point['temp']) / temp_range * speed_range)
                                else:
                                    target_fan_speed_val = lower_point['speed']
                            
                            # Clamp to valid range and convert to int
                            target_fan_speed_val = max(0, min(100, int(target_fan_speed_val)))
                            print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) CURVE mode. Fan: {target_fan_speed_val}%", flush=True)
                            ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                            target_fan_speed_display = target_fan_speed_val
                        else:
                            # Shouldn't reach here due to validation, but fallback to simple mode
                            print(f"[WARNING] Fan curve invalid. Falling back to simple mode.", flush=True)
                            low_thresh_c = addon_options["low_temp_threshold_c"]
                            if hottest_cpu_temp_c >= low_thresh_c:
                                target_fan_speed_val = addon_options["high_temp_fan_speed_percent"]
                                ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                                target_fan_speed_display = target_fan_speed_val
                            else:
                                target_fan_speed_val = addon_options["base_fan_speed_percent"]
                                ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                                target_fan_speed_display = target_fan_speed_val
                    else:
                        # Simple mode: 3-tier control (default)
                        low_thresh_c = addon_options["low_temp_threshold_c"]
                        if hottest_cpu_temp_c >= low_thresh_c:
                            target_fan_speed_val = addon_options["high_temp_fan_speed_percent"]
                            print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) >= LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                            ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                            target_fan_speed_display = target_fan_speed_val
                        else: 
                            target_fan_speed_val = addon_options["base_fan_speed_percent"]
                            print(f"[{log_level.upper()}] CPU ({hottest_cpu_temp_c}°C) < LOW ({low_thresh_c}°C). Fan: {target_fan_speed_val}%", flush=True)
                            ipmi_manager.apply_user_fan_control_profile(target_fan_speed_val)
                            target_fan_speed_display = target_fan_speed_val
                else:
                    print(f"[WARNING] Hottest CPU temp N/A. Applying Dell auto fans for safety.", flush=True)
                    ipmi_manager.apply_dell_fan_control_profile()
                    target_fan_speed_display = "Dell Auto (Safety)"
            else:
                print(f"[{log_level.upper()}] Fan control is disabled. Setting to Dell Auto.", flush=True)
                ipmi_manager.apply_dell_fan_control_profile()
                target_fan_speed_display = "Dell Auto (Disabled)"
            
            # --- Update Shared Status File for Web UI ---
            current_parsed_status_for_file = {
                "cpu_temps_c": cpu_temps_list_c,
                "hottest_cpu_temp_c": hottest_cpu_temp_c,
                "inlet_temp_c": parsed_temperatures_c.get("inlet_temp"),
                "exhaust_temp_c": parsed_temperatures_c.get("exhaust_temp"),
                "target_fan_speed_percent": target_fan_speed_display,
                "actual_fan_rpms": parsed_fan_rpms,
                "power_consumption_watts": power_consumption_watts,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S %Z")
            }
            save_current_status_to_file(current_parsed_status_for_file)

            # --- MQTT State Publishing ---
            if mqtt_handler and mqtt_handler.is_connected:
                # (Keep existing MQTT state publishing logic for temps, target fan speed, hottest cpu, power, fan rpms)
                # CPU Temps
                for i, cpu_temp_val in enumerate(cpu_temps_list_c):
                    mqtt_handler.publish_sensor_state(sensor_type_slug=f"cpu_{i}_temp", value_dict={"temperature": cpu_temp_val})
                # Inlet/Exhaust
                if parsed_temperatures_c.get("inlet_temp") is not None:
                     mqtt_handler.publish_sensor_state(sensor_type_slug="inlet_temp", value_dict={"temperature": parsed_temperatures_c["inlet_temp"]})
                if parsed_temperatures_c.get("exhaust_temp") is not None:
                     mqtt_handler.publish_sensor_state(sensor_type_slug="exhaust_temp", value_dict={"temperature": parsed_temperatures_c["exhaust_temp"]})
                # Hottest CPU
                if hottest_cpu_temp_c is not None:
                    mqtt_handler.publish_sensor_state(sensor_type_slug="hottest_cpu_temp", value_dict={"temperature": hottest_cpu_temp_c})
                # Target Fan Speed
                if target_fan_speed_display not in ["N/A", "Dell Auto", "Dell Auto (Safety)"]:
                    try: # Ensure it's an int before publishing if template expects number
                        mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": int(target_fan_speed_display)})
                    except ValueError:
                        mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": None}) # Or publish the string "Auto"
                else: 
                     mqtt_handler.publish_sensor_state(sensor_type_slug="target_fan_speed", value_dict={"speed": None}) 
                # Power Consumption
                if power_consumption_watts is not None:
                    mqtt_handler.publish_sensor_state(sensor_type_slug="power_consumption", value_dict={"power": power_consumption_watts})
                # Actual Fan RPMs
                for i, fan_info in enumerate(parsed_fan_rpms):
                    fan_name = fan_info["name"]
                    safe_fan_name_slug = re.sub(r'[^a-zA-Z0-9_]+', '_', fan_name).lower().strip('_')
                    if not safe_fan_name_slug: safe_fan_name_slug = f"fan_{i}"
                    mqtt_handler.publish_sensor_state(sensor_type_slug=f"fan_{safe_fan_name_slug}_rpm", value_dict={"rpm": fan_info["rpm"]})

            print(f"[{log_level.upper()}] --- Cycle {loop_count + 1} End ---", flush=True)
        
        except Exception as cycle_exception: # Catch exceptions within the cycle's work
            print(f"[ERROR] Unhandled exception within cycle {loop_count + 1}: {cycle_exception}", flush=True)
            import traceback
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            # Decide if this error is critical enough to stop the whole add-on, or just skip a cycle
            # For now, it will just log and proceed to the sleep calculation.

        # --- Sleep Logic ---
        # This calculation should now always happen, even if there was an error in the 'try' block above.
        time_taken = time.time() - start_time
        sleep_duration = max(0.1, addon_options["check_interval_seconds"] - time_taken)
        
        print(f"[{log_level.upper()}] Cycle {loop_count + 1} took {time_taken:.2f}s. Sleeping for {sleep_duration:.2f}s.", flush=True)
        loop_count += 1

        for _ in range(int(sleep_duration / 0.1)): # Check running flag frequently
            if not running: break
            time.sleep(0.1)
        if not running: break

# --- Global mqtt_handler_instance ---
mqtt_handler_instance = None

if __name__ == "__main__":
    print("[MAIN] ===== HA iDRAC Controller Python Application Starting =====", flush=True)
    
    mqtt_handler_instance = mqtt_client.MqttClient() # Create instance early

    load_and_configure(mqtt_handler_instance) # Pass instance to configure it

    if addon_options.get("mqtt_host") and addon_options["mqtt_host"] != "YOUR_MQTT_BROKER_IP_OR_HOSTNAME":
        # Client ID should be unique, can be based on some config or generated
        mqtt_handler_instance.client_id = f"ha_idrac_controller_{addon_options.get('idrac_ip','unknown').replace('.','_')}"
        mqtt_handler_instance.connect()
    else:
        print("[INFO] MQTT host not configured or is default placeholder. MQTT client will not connect.", flush=True)
        mqtt_handler_instance = None 

    web_server_port = 8099 
    web_thread = threading.Thread(target=web_server.run_web_server, args=(web_server_port,), daemon=True)
    web_thread.start()
    print(f"[MAIN] Admin Web Panel server starting in background thread on port {web_server_port}...", flush=True)

    try:
        main_control_loop(mqtt_handler_instance)
    except Exception as e:
        print(f"[FATAL] Unhandled exception in main execution: {e}", flush=True)
        import traceback; traceback.print_exc(file=sys.stdout); sys.stdout.flush()
    finally:
        print("[MAIN] Main execution finished. Initiating final cleanup...", flush=True)
        if addon_options.get("idrac_ip") and ipmi_manager._IPMI_BASE_ARGS: 
            print("[MAIN] Attempting to set fans to Dell default profile...", flush=True)
            ipmi_manager.apply_dell_fan_control_profile()
        if mqtt_handler_instance and getattr(mqtt_handler_instance, 'is_connected', False):
            mqtt_handler_instance.disconnect()
        print("[MAIN] ===== HA iDRAC Controller Python Application Stopped =====", flush=True)
        sys.stdout.flush()