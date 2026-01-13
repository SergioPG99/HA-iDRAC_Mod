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