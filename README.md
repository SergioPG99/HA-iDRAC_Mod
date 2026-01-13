# HA-iDRAC Project

This repository contains custom Home Assistant add-ons for managing and monitoring Dell PowerEdge servers via their iDRAC interface.

## Available Add-ons

1.  **HA iDRAC Controller (Stable)**
    * Monitors key server metrics (CPU temperature, fan speeds, power consumption) and controls fan speeds based on CPU temperature.
    * Supports **Simple** (3-tier) and **Curve** (multi-point interpolation) fan control modes.
    * For detailed information, installation, and configuration, please see the [**Stable Add-on README](./ha-idrac-controller/README.md)**.

2.  **HA iDRAC Controller (Development Version)**
    * **<font color="orange">⚠️ DEVELOPMENT VERSION - USE WITH CAUTION! ⚠️</font>**
    * This is the active development version, including the latest features and bug fixes, but may also be unstable. Intended for testing and feedback.
    * Adds **Target Temperature** (PID controller) mode for precise dynamic fan control.
    * For detailed information, installation, and configuration, please see the [**Development Add-on README](./ha-idrac-controller-dev/README.md)**.

3.  **HA iDRAC Controller Multi-Server**
    * **<font color="orange">⚠️ DEVELOPMENT VERSION - USE WITH CAUTION! ⚠️</font>**
    * Control and monitor **multiple Dell PowerEdge servers** from a single add-on instance.
    * Each server can be configured independently with its own fan control settings.
    * Supports all fan control modes: **Simple**, **Curve**, and **Target Temperature** (PID).
    * For detailed information, installation, and configuration, please see the [**Multi-Server Add-on README](./ha-idrac-controller-multi-server/README.md)**.

## Fan Control Features

This project offers three different fan control modes with varying levels of precision:

### 1. Simple Mode (3-Tier Control)
* **Available in:** All versions (Stable, Dev, Multi-Server)
* **How it works:** Uses three temperature thresholds:
  * **Base Speed**: Applied when CPU temperature is below the low threshold
  * **High Speed**: Applied when CPU temperature is between low and critical thresholds
  * **Critical (Dell Auto)**: Returns control to iDRAC when temperature reaches critical threshold
* **Best for:** Simple, reliable fan control with minimal configuration

### 2. Curve Mode (Multi-Point Interpolation)
* **Available in:** All versions (Stable, Dev, Multi-Server)
* **How it works:** Define multiple temperature/fan-speed points, and the system will interpolate linearly between them
* **Example:** `[{temp: 40, speed: 20}, {temp: 50, speed: 35}, {temp: 60, speed: 60}, {temp: 65, speed: 80}]`
* **Best for:** Smooth, gradual fan speed transitions and precise control across different temperature ranges

### 3. Target Temperature Mode (PID Controller)
* **Available in:** Dev and Multi-Server versions only
* **How it works:** Uses a PID (Proportional-Integral-Derivative) controller to automatically adjust fan speeds to maintain a target CPU temperature
* **Configuration:** Set your desired target temperature and PID tuning parameters (Kp, Ki, Kd)
* **Best for:** Maximum precision and automated temperature regulation with minimal temperature fluctuation
* **Status:** ✅ Fully implemented and functional with persistent state management

#### PID Controller Implementation Details
The PID controller is a sophisticated control loop mechanism that:
- **Proportional (P)**: Reacts to the current temperature error (difference from target)
- **Integral (I)**: Accumulates past errors to eliminate steady-state error (includes anti-windup protection)
- **Derivative (D)**: Predicts future error based on rate of change to prevent overshoot

**Key Features:**
- Persistent state storage: PID integral term is saved to `/data/pid_states.json` and restored on restart
- Configurable gains: Kp, Ki, and Kd can be tuned per server
- Safety limits: Output is clamped between 15% and 95% to protect hardware
- Anti-windup: Prevents integral term from growing too large

**Default PID Settings:**
- Target Temperature: 55°C
- Kp (Proportional Gain): 4.0
- Ki (Integral Gain): 0.2
- Kd (Derivative Gain): 0.1

These values provide a good starting point for most Dell PowerEdge servers, but may need adjustment based on your specific hardware and thermal characteristics.

## Dynamic Fan Control Development Status

### Evolution of Fan Control Precision

The project has evolved through three stages of increasing precision:

1. **Initial Stage - Simple 3-Tier Control** ✅ Complete
   - Basic temperature thresholds with discrete fan speed changes
   - Works well for most use cases but can cause sudden fan speed changes

2. **Intermediate Stage - Curve Mode** ✅ Complete
   - Multi-point temperature/fan-speed interpolation
   - Smooth transitions between different temperature zones
   - More precise than 3-tier but still reactive rather than predictive

3. **Advanced Stage - PID Controller** ✅ Complete
   - Fully dynamic temperature regulation
   - Automatically adjusts to maintain exact target temperature
   - Predictive behavior reduces temperature fluctuations
   - Persistent state allows seamless operation across restarts
   - **Implementation Status**: Fully functional in Dev and Multi-Server versions

### Current Development Focus

The PID controller represents the most advanced fan control available in this project. It provides:
- More precise temperature control than the initial 3-tier system
- Smoother fan speed adjustments than curve mode
- Automated adaptation to changing thermal loads
- Professional-grade temperature regulation

All three modes remain available to users, allowing them to choose the level of complexity and precision that best suits their needs.

## Adding this Repository to Home Assistant

To install these add-ons:

1.  In Home Assistant, navigate to **Settings > Add-ons**.
2.  Click on the **"ADD-ON STORE"** button.
3.  Click the **three-dots menu (⋮)** in the top right and select **"Repositories"**.
4.  Add the URL of this repository:
    ```
    https://github.com/SergioPG99/HA-iDRAC_Mod
    ```
5.  Click **"ADD"** and then **"CLOSE"**.
6.  The add-ons from this repository will now be available in the store under the name specified in the `repository.yaml` file (e.g., "SergioPG99's iDRAC Add-on"). Select the specific version you wish to install.

## Issues and Contributions

Please report any issues or make contributions via the [GitHub Issues page](https://github.com/SergioPG99/HA-iDRAC_Mod/issues), clearly stating which version of the add-on you are using.

## License

This project and its components are under the [MIT License](./LICENSE).