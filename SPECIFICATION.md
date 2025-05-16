# MQTT LCARS Alert Panel - Specification

## 1. Project Overview

**Project Name:** MQTT LCARS Alert Panel
**Objective:** To create a visually engaging and informative display panel for a Raspberry Pi with a TFT screen, showing real-time alerts and messages received via MQTT, styled with an LCARS (Library Computer Access/Retrieval System) theme.

## 2. Core Features

*   **MQTT v5 Client:** Utilizes MQTT protocol version 5 for communication. (Implemented)
*   **Wildcard Topic Subscription:** Listens to a range of topics under a configurable prefix. (Implemented)
*   **Structured Message Parsing:** Processes messages formatted in JSON, allowing for richer data content. Also handles plaintext messages, deriving source from topic. (Implemented)
*   **LCARS-Themed User Interface:** Presents information within a graphical interface inspired by Star Trek's LCARS design. (Implemented)
*   **Rolling Message Display:** Shows a continuously updating stream of the most recent messages. (Implemented)
*   **Persistent Error/Warning Messages:** "Sticky" messages of high importance (errors, warnings) remain on screen until manually cleared. (Not Yet Implemented)
*   **Touchscreen Interaction:** Allows clearing of persistent messages via an on-screen button (requires touchscreen). (Placeholders Implemented)
*   **Configurability:** Key parameters (MQTT details, topic, title, fonts, control channel behavior) are configurable via environment variables. (Implemented)
*   **Control Channel & Debugging:** MQTT-based control for debugging and message logging. (Implemented)

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
        *   `"control"`: Used for messages originating from the control channel, displayed with a specific color.
    *   `timestamp` (string/number, optional): ISO 8601 formatted timestamp (e.g., "YYYY-MM-DDTHH:MM:SSZ") or Unix epoch. If not provided, the panel will use the message arrival time.
*   **Error Handling & Plaintext:**
    *   Messages not conforming to valid JSON or missing the mandatory `message` field will be treated as plaintext.
    *   For plaintext messages, the `source` is derived from the MQTT topic suffix relative to `MQTT_TOPIC_PREFIX`. `importance` defaults to "info".
    *   The entire payload is treated as the `message` text.

### 3.3. Display and User Interface (LCARS Theme)
*   **General Layout:**
    *   Inspired by LCARS design principles: characteristic shapes (rounded ends, elbows), color palette, and typography.
    *   The screen is structured with a top status bar, a central message display area, and a bottom control bar.
    *   **Top Bar:** A horizontal bar at the top of the screen.
        *   Contains a left rounded terminator `(]`, a central segment displaying the title "EVENT LOG" (using `TITLE_FONT`), and a right rounded terminator `[)`.
        *   Bar elements typically use `LCARS_ORANGE`.
    *   **Bottom Bar:** A horizontal bar at the bottom of the screen.
        *   Contains a left rounded terminator `(]`, followed by the label "MQTT STREAM" (using `TITLE_FONT`).
        *   To the right of the label, three placeholder square buttons: `[CLEAR]`, `[RELATIVE]`, `[CLOCK]` (using `BODY_FONT` for labels, distinct background colors).
        *   The bar is completed with a right rounded terminator `[)`.
        *   Bar elements typically use `LCARS_ORANGE`, with buttons having specific LCARS colors (e.g., red, blue, yellow). Button labels are black.
    *   **Message Display Area:** The central portion of the screen between the top and bottom bars.
*   **Title Bar:**
    *   The UI uses fixed titles "EVENT LOG" (top bar) and "MQTT STREAM" (bottom bar label). The previously defined `LCARS_TITLE_TEXT` environment variable has been removed as it was not used for rendering.
*   **Font:**
    *   `LCARS_FONT_PATH` (string, environment variable): Path to a `.ttf` LCARS-style font file. This font is used for titles and messages. Fallback mechanisms are in place if the specified font is not found.
    *   `TITLE_FONT` and `BODY_FONT` are used for different UI text elements.
*   **Colors:** A predefined LCARS color palette is used (e.g., oranges, blues, creams, specific button colors). Key colors are defined as constants in the script.
*   **Message Area (3-Column Layout):**
    *   Occupies the space between the top and bottom bars.
    *   Displays a list of messages, with the most recent ones appearing at the bottom and older ones scrolling off (unless sticky).
    *   **Message Format on Screen (3 Columns):**
        1.  **Source Column (Left):** Displays `msg_obj.get('source', 'N/A')`. Fixed width (e.g., 20 characters or ~1/4 screen width), truncated with "..." if too long. Left-aligned.
        2.  **Message Column (Center):** Displays `msg_obj.get('text', '')`. Uses remaining width between Source and Timestamp columns. Text is wrapped to fit. Left-aligned.
        3.  **Timestamp Column (Right):** Displays message timestamp, formatted as `HH:MM:SS`. Right-aligned within its allocated space near the screen edge.
    *   Messages with `importance` "warning" or "error" may have distinct visual cues (e.g., background color highlight, prefix icon) - *to be implemented with sticky messages*.
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
    *   Tapping this button will remove all currently displayed sticky ("warning" and "error") messages. Normal "info" messages are unaffected. This button is currently a visual placeholder.
*   **Control Channel & Debugging (Implemented):**
    *   **Control Topic:** The panel subscribes to a dedicated control topic prefix, configurable via `MQTT_CONTROL_TOPIC_PREFIX` (e.g., `lcars/<hostname>/#`, where `<hostname>` is the device's hostname). MQTT topic names can contain hyphens. (Implemented)
    *   **Control Message Display:**
        *   Optionally, messages received on the control channel can be displayed in the main message list. This is controlled by the `LOG_CONTROL_MESSAGES` environment variable (defaults to true). (Implemented)
        *   If displayed, the message `source` will be `LCARS/<suffix>`, where `<suffix>` is the part of the topic after the control prefix. The message `text` will be the raw payload of the control message. (Implemented)
        *   These messages will have an `importance` of `"control"` and be displayed with a distinct color (e.g., `LCARS_CYAN`). (Implemented)
    *   **Supported Control Commands (payload is the message content):** (Implemented)
        *   Topic Suffix: `debug-layout`
            *   Payload `"enable"`: Turns on layout debugging.
            *   Payload `"disable"` or empty string: Turns off layout debugging.
        *   Topic Suffix: `log-control`
            *   Payload `"enable"`: Control messages will be added to the main message list.
            *   Payload `"disable"` or empty string: Control messages will not be added to the main message list.
    *   **Layout Debugging Visuals:** (Implemented)
        *   When enabled, all standard LCARS UI elements (bars, endcaps, buttons, text elements drawn by `draw_lcars_shape` and `draw_text_in_rect`) will have their bounding boxes rendered as a 1-pixel green outline.
        *   Additionally, the defined columns within the message display area (Source, Message, Timestamp) will have their bounding boxes rendered as a 1-pixel pink outline. A blue vertical line indicates the calculated message wrapping point in the message column.
*   **Relative Timestamp Button (`[RELATIVE]`):**
    *   A visually distinct button element in the bottom LCARS bar, labeled "RELATIVE".
    *   **Function (to be implemented):** Toggles the display format of timestamps in the message area.
        *   **Absolute Mode:** Timestamps show the actual time of the event (e.g., "12:45:00").
        *   **Relative Mode:** Timestamps show how long ago the message arrived (e.g., "-00:05:30" for 5 minutes and 30 seconds ago).
    *   Requires touchscreen input. This button is currently a visual placeholder.
*   **Clock Mode Button (`[CLOCK]`):**
    *   A visually distinct button element in the bottom LCARS bar, labeled "CLOCK".
    *   **Function (to be implemented):** Switches the entire display from the event log view to a full-screen LCARS-themed clock.
        *   Tapping it again (or another defined interaction) would switch back to the event log view.
    *   Requires touchscreen input. This button is currently a visual placeholder.
*   **Alternative Clearing Mechanism (MQTT Command):**
    *   As a fallback or for systems without touch, a specific MQTT message can clear sticky alerts.
    *   Topic: `MQTT_TOPIC_PREFIX/control` (or similar configurable control topic).
    *   Payload: `{"command": "clear_sticky"}`. (This remains relevant for clearing sticky messages, the `[CLEAR]` button will eventually perform a similar action for all messages).

### 3.5. Configuration
Environment variables will be the primary method of configuration, loaded from a file (e.g., `/home/pi/.config/mqtt_alert_panel.env`).
*   `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`
*   `MQTT_TOPIC_PREFIX`
*   `MQTT_CONTROL_TOPIC_PREFIX` (e.g., `lcars/alert-panel/` or `lcars/<hostname>/`)
*   `LOG_CONTROL_MESSAGES` (boolean, e.g., `true` or `false`, defaults to `true`. Controls if messages from `MQTT_CONTROL_TOPIC_PREFIX` are displayed in the event log)
*   `LCARS_FONT_PATH` (Path to the LCARS font file)
*   `MAX_MESSAGES_IN_STORE` (Integer, maximum number of messages to keep in the rolling display buffer)
*   `DISPLAY_ROTATE` (Controls screen rotation: 0, 90, 180, 270)
*   (Potentially others for fine-tuning colors, timestamp formats).

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
