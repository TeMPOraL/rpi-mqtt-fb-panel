# MQTT LCARS Alert Panel - Specification

## 1. Project Overview

**Project Name:** MQTT LCARS Alert Panel
**Objective:** To create a visually engaging and informative display panel for a Raspberry Pi with a TFT screen, showing real-time alerts and messages received via MQTT, styled with an LCARS (Library Computer Access/Retrieval System) theme.

## 2. Core Features

*   **MQTT v5 Client:** Utilizes MQTT protocol version 5 for communication.
*   **Wildcard Topic Subscription:** Listens to a range of topics under a configurable prefix.
*   **Structured Message Parsing:** Processes messages formatted in JSON, allowing for richer data content.
*   **LCARS-Themed User Interface:** Presents information within a graphical interface inspired by Star Trek's LCARS design.
*   **Rolling Message Display:** Shows a continuously updating stream of the most recent messages.
*   **Persistent Error/Warning Messages:** "Sticky" messages of high importance (errors, warnings) remain on screen until manually cleared.
*   **Touchscreen Interaction:** Allows clearing of persistent messages via an on-screen button (requires touchscreen).
*   **Configurability:** Key parameters (MQTT details, topic, title, fonts) are configurable via environment variables.

## 3. Detailed Functionality

### 3.1. MQTT Connection & Subscription
*   **Protocol:** MQTT v5.
*   **Configuration:**
    *   `MQTT_HOST`: Broker hostname or IP address.
    *   `MQTT_PORT`: Broker port (default 1883, or 8883 for TLS).
    *   `MQTT_USER`: Username for MQTT authentication.
    *   `MQTT_PASS`: Password for MQTT authentication.
    *   `MQTT_TOPIC_PREFIX`: The base topic path for wildcard subscription (e.g., `home/lcars_panel/`). The panel will subscribe to `MQTT_TOPIC_PREFIX#`.
*   **Behavior:** Connects to the specified MQTT broker and subscribes to all topics under the given prefix. Handles connection retries.

### 3.2. Message Format and Parsing
*   **Format:** JSON.
*   **Payload Structure (Example):**
    ```json
    {
      "message": "Shields at 75%",
      "source": "USS Defiant - Engineering",
      "importance": "info",
      "timestamp": "2024-07-15T10:30:00Z"
    }
    ```
*   **Fields:**
    *   `message` (string, **mandatory**): The primary text content of the alert/message.
    *   `source` (string, optional): Originating device, service, or entity. Defaults to "Unknown".
    *   `importance` (string, optional): Message severity. Accepted values:
        *   `"info"` (default): Standard informational message.
        *   `"warning"`: Indicates a potential issue or caution. Becomes a sticky message.
        *   `"error"`: Indicates an error or critical failure. Becomes a sticky message.
    *   `timestamp` (string/number, optional): ISO 8601 formatted timestamp (e.g., "YYYY-MM-DDTHH:MM:SSZ") or Unix epoch. If not provided, the panel will use the message arrival time.
*   **Error Handling:** Messages not conforming to valid JSON or missing the mandatory `message` field will be logged (if logging is implemented) and discarded without display.

### 3.3. Display and User Interface (LCARS Theme)
*   **General Layout:**
    *   Inspired by LCARS design principles: characteristic shapes (rounded ends, elbows), color palette, and typography.
    *   Screen divided into a header/title area, a main message display area, and potentially a small control area (for the clear button).
*   **Title Bar:**
    *   `LCARS_TITLE_TEXT` (string, environment variable): A fixed title displayed prominently (e.g., top of the screen, right-aligned). Example: "STARBASE 74 - ALERT STATUS".
*   **Font:**
    *   `LCARS_FONT_PATH` (string, environment variable): Path to a `.ttf` LCARS-style font file. This font will be used for the title and messages.
*   **Colors:** A predefined LCARS color palette will be used (e.g., oranges, blues, creams). Specific colors for text, backgrounds, and UI elements.
*   **Message Area:**
    *   Occupies the largest portion of the screen (e.g., bottom 3/4).
    *   Displays a list of messages, with the most recent ones appearing and older ones scrolling off (unless sticky).
    *   **Message Format on Screen (Example):**
        `[HH:MM:SS] [SOURCE] Message text content here...`
        (Timestamp format might be configurable or simplified from the input).
    *   Messages with `importance` "warning" or "error" may have distinct visual cues (e.g., background color highlight, prefix icon).
*   **Persistent (Sticky) Messages:**
    *   Messages marked as "warning" or "error" will become "sticky."
    *   When a sticky message scrolls to the top of the active message display area, it will remain fixed there.
    *   Subsequent sticky messages will accumulate below previous ones, reducing the available space for normal, scrolling "info" messages.
*   **Display Rotation:**
    *   `DISPLAY_ROTATE` (integer, environment variable): 0, 90, 180, or 270 degrees.

### 3.4. Interaction
*   **Touchscreen Button (Clear Sticky Messages):**
    *   A visually distinct button element within the LCARS UI (e.g., labeled "CLEAR ALERTS").
    *   Requires a touchscreen configured for input (e.g., via `evdev`).
    *   Tapping this button will remove all currently displayed sticky ("warning" and "error") messages. Normal "info" messages are unaffected.
*   **Alternative Clearing Mechanism (MQTT Command):**
    *   As a fallback or for systems without touch, a specific MQTT message can clear sticky alerts.
    *   Topic: `MQTT_TOPIC_PREFIX/control` (or similar configurable control topic).
    *   Payload: `{"command": "clear_sticky"}`.

### 3.5. Configuration
Environment variables will be the primary method of configuration, loaded from a file (e.g., `/home/pi/.config/mqtt_alert_panel.env`).
*   `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`
*   `MQTT_TOPIC_PREFIX`
*   `LCARS_TITLE_TEXT`
*   `LCARS_FONT_PATH`
*   `DISPLAY_ROTATE`
*   (Potentially others for fine-tuning colors, timestamp formats, max number of messages if not dynamically calculated).

### 3.6. Operational Modes (Command-line Arguments)
*   **Default Mode:** Runs the full application, connects to MQTT, displays messages.
    `python3 mqtt_fb_panel.py`
*   **Debug Mode:**
    `python3 mqtt_fb_panel.py --debug`
    Displays sample content/UI layout for a short period then exits. Useful for testing visuals without full MQTT setup.
*   **Probe Mode:**
    `python3 mqtt_fb_panel.py --probe [square|circle] [--fill]`
    Draws a test shape then exits (retains current probe functionality).

## 4. System and Platform
*   **Target Platform:** Raspberry Pi 2 Model B V1.1 (or similar ARMv7 32-bit systems).
*   **Operating System:** Raspbian GNU/Linux 11 (Bullseye) or compatible.
*   **Display:** Direct framebuffer access (e.g., `/dev/fb0`) for a TFT display.
*   **Dependencies:**
    *   `python3`
    *   `paho-mqtt` (Python MQTT client library)
    *   `Pillow` (Python Imaging Library)
    *   `numpy`
    *   `python-evdev` (for touchscreen input)
    *   LCARS-style `.ttf` font file (user-provided).
*   **Service Management:** Designed to be run as a systemd service, with an example service file provided.

## 5. Non-Goals (Initially)
*   Complex animations beyond simple scrolling.
*   On-screen configuration UI.
*   Support for multiple font styles simultaneously beyond the primary LCARS font.
*   Storing messages persistently across reboots (beyond what's in memory).
*   Sound alerts.
