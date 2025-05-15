# MQTT LCARS Alert Panel Implementation Plan

This document outlines the phased implementation plan for enhancing the MQTT Alert Panel.

## Phase 1: MQTT & Basic Message Handling
*   [x] **Implement MQTTv5:**
    *   [x] Update `paho-mqtt` client initialization to specify `protocol=mqtt.MQTTv5`.
    *   [ ] Verify MQTTv5 features if any specific ones are leveraged (initially, just compatibility).
*   [x] **Wildcard Topic Subscription:**
    *   [x] Add new environment variable `MQTT_TOPIC_PREFIX` (e.g., `home/lcars_panel/`).
    *   [x] Modify `client.subscribe()` to use the prefix with a wildcard (e.g., `home/lcars_panel/#`).
    *   [x] Remove/deprecate `TOPIC_TITLE` and `TOPIC_BODY` for subscription purposes.
*   [x] **JSON Message Parsing:**
    *   [x] In `on_mqtt` callback, attempt to parse `msg.payload.decode()` using `json.loads()`.
    *   [x] Define initial expected JSON structure (e.g., `{"message": "text", "importance": "info", "source": "device_name"}`).
    *   [x] Implement error handling for malformed JSON.
*   [x] **Message Storage:**
    *   [x] Replace `current = {"title": "", "body": ""}` with a list or `collections.deque` to store incoming message objects (parsed from JSON).
    *   [x] Each item in the list should be a dictionary or a simple class instance representing the parsed message.

## Phase 2: Rolling Display & Fixed Title
*   [ ] **Fixed Title:**
    *   [ ] Add new environment variable `LCARS_TITLE_TEXT` for the fixed title.
    *   [ ] Modify rendering logic to display this title (e.g., top-right aligned).
*   [ ] **Rolling Message Display:**
    *   [ ] Rewrite the `render` function.
    *   [ ] Iterate through the stored messages (newest first at the bottom, or oldest first from the top).
    *   [ ] Calculate how many messages fit on screen based on font size and available vertical space (initially using `BODY_FONT`).
    *   [ ] Render each message's text.
    *   [ ] Ensure the display updates dynamically as new messages arrive.

## Phase 3: LCARS Visuals
*   [ ] **LCARS Font:**
    *   [ ] Add new environment variable `LCARS_FONT_PATH` for the `.ttf` font file.
    *   [ ] User to provide an LCARS-style `.ttf` font.
    *   [ ] Update font loading (`ImageFont.truetype()`) to use this new font for messages and title.
    *   [ ] Adjust font sizes as needed.
*   [ ] **Basic LCARS Graphics:**
    *   [ ] Define LCARS color palette (new constants).
    *   [ ] In the `render` function, add `draw.rectangle()`, `draw.line()` calls to create static LCARS elements (e.g., header bar, side elements, message area borders).
    *   [ ] Constrain message rendering to the designated message area within the LCARS layout.

## Phase 4: Sticky Messages
*   [ ] **Message Importance Handling:**
    *   [ ] Ensure JSON messages can include an `importance` field ("info", "warning", "error").
    *   [ ] Store this importance level with each message object.
*   [ ] **Data Storage for Sticky Messages:**
    *   [ ] Decide on a strategy:
        *   Separate list for sticky messages.
        *   Attribute/flag on message objects in a single list.
*   [ ] **Rendering Sticky Messages:**
    *   [ ] Sticky messages ("error", "warning") are rendered in a persistent area (e.g., top of the message list).
    *   [ ] They do not scroll off screen.
    *   [ ] The space for normal rolling messages dynamically shrinks as sticky messages accumulate.
    *   [ ] Consider distinct visual styling for sticky messages (e.g., background color, icon).

## Phase 5: Clearing Mechanism
*   [ ] **MQTT-based Clearing (Initial):**
    *   [ ] Define a specific MQTT topic and message payload to trigger clearing of sticky messages (e.g., topic `home/lcars_panel/control`, payload `{"command": "clear_sticky"}`).
    *   [ ] Update `on_mqtt` to handle this command.
    *   [ ] Implement logic to remove/clear all sticky messages from the store and re-render.

## Phase 6: Touchscreen Input (Advanced)
*   [ ] **Input Library Integration:**
    *   [ ] Add `python-evdev` as a dependency.
    *   [ ] Research and implement reading touch events from `/dev/input/eventX`.
*   [ ] **Event Loop Modification:**
    *   [ ] Change `client.loop_forever()` to `client.loop_start()`.
    *   [ ] Create a main application loop that polls for:
        *   MQTT messages (or relies on `paho-mqtt` background thread and callbacks).
        *   Touchscreen input events.
*   [ ] **Button Definition & Handling:**
    *   [ ] Define screen coordinates for a "clear sticky messages" button within the LCARS UI.
    *   [ ] Render this button visually.
    *   [ ] When a touch event occurs within the button's coordinates, trigger the clearing action for sticky messages.
*   [ ] **Debouncing/Event Filtering:** Implement if necessary for touch input.

## Post-Implementation
*   [ ] **Documentation Update:**
    *   [ ] Update `README.org` with new features, configuration, and setup.
    *   [ ] Update `mqtt_alert_panel.env.example`.
*   [ ] **Code Cleanup & Refinement:**
    *   [ ] Review for performance, especially on RPi 2.
    *   [ ] Refactor for clarity and maintainability.
*   [ ] **Update `AI.md`:**
    *   [ ] Mark completed phases in `PLAN.md`.
    *   [ ] Update project structure if it evolves.
