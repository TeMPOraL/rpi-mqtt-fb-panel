# MQTT LCARS Alert Panel Implementation Plan

This document outlines the phased implementation plan for enhancing the MQTT Alert Panel.

## Phase 1: MQTT & Basic Message Handling
*   [x] **Implement MQTTv5:**
    *   [x] Update `paho-mqtt` client initialization to specify `protocol=mqtt.MQTTv5`.
    *   [x] Verify MQTTv5 features if any specific ones are leveraged (initially, just compatibility).
*   [x] **Wildcard Topic Subscription:**
    *   [x] Add new environment variable `MQTT_TOPIC_PREFIX` (e.g., `home/lcars_panel/`).
    *   [x] Modify `client.subscribe()` to use the prefix with a wildcard (e.g., `home/lcars_panel/#`).
    *   [x] Remove/deprecate `TOPIC_TITLE` and `TOPIC_BODY` for subscription purposes.
*   [x] **JSON Message Parsing:**
    *   [x] In `on_mqtt` callback, attempt to parse `msg.payload.decode()` using `json.loads()`.
    *   [x] Define initial expected JSON structure (e.g., `{"message": "text", "importance": "info", "source": "device_name"}`).
    *   [x] Implement error handling for malformed JSON (falls back to raw text).
    *   [x] Derive source from topic suffix for plaintext MQTT messages.
*   [x] **Message Storage:**
    *   [x] Replace `current = {"title": "", "body": ""}` with a list or `collections.deque` to store incoming message objects (parsed from JSON).
    *   [x] Each item in the list should be a dictionary or a simple class instance representing the parsed message (`Message` dataclass).

## Phase 2: Rolling Display & Fixed Title
*   [x] **Fixed Title:**
    *   [x] Add new environment variable `LCARS_TITLE_TEXT` for the fixed title (Note: UI uses hardcoded "EVENT LOG" and "MQTT STREAM" currently).
    *   [x] Modify rendering logic to display this title (e.g., top-right aligned).
*   [x] **Rolling Message Display:**
    *   [x] Rewrite the `render` function (`render_messages`).
    *   [x] Iterate through the stored messages (oldest first from the top, displaying most recent that fit).
    *   [x] Calculate how many messages fit on screen based on font size and available vertical space (initially using `BODY_FONT`).
    *   [x] Render each message's text (formatted with timestamp, source, and wrapped content).
    *   [x] Ensure the display updates dynamically as new messages arrive.

## Phase 3: LCARS Visuals
*   [x] **LCARS Font:** (User reported completing initial font setup)
    *   [x] Consider adding `LCARS_FONT_PATH` environment variable for easier font switching if current hardcoded path is not final.
    *   [x] User has provided and configured an LCARS-style `.ttf` font.
    *   [x] Font loading updated by user.
    *   [x] Font sizes may need further adjustment as UI evolves.
    *   [x] `LCARS_FONT_PATH` environment variable added for font configuration.
*   [x] **Basic LCARS Graphics (Complete):**
    *   [x] Define extended LCARS color palette (new constants added).
    *   [x] Implement helper function for drawing LCARS shapes (rectangles with optional rounded ends).
    *   [x] Redesign `render` function for new LCARS layout:
        *   [x] Draw top bar with "EVENT LOG" label and rounded terminators `(]` and `[)`.
        *   [x] Draw bottom bar with "MQTT STREAM" label, placeholder buttons `[CLEAR]`, `[RELATIVE]`, `[CLOCK]`, and terminators `(]` and `[)`.
        *   [x] Implement 3-column message display (Source, Message, Timestamp) in the central area.
    *   [x] Constrain message rendering to the designated message area.
    *   [x] Refine visual alignment and spacing of all elements.

## Phase 3.5: Control Channel & Debugging (Feature Complete)
*   [x] **Control Topic Subscription:**
    *   [x] Subscribe to `MQTT_CONTROL_TOPIC_PREFIX` (e.g., `lcars/<hostname>/#`).
*   [x] **Control Message Handling & Display:**
    *   [x] Configurable display of control messages via `LOG_CONTROL_MESSAGES` env var.
    *   [x] Source formatted as `LCARS/<suffix>`.
    *   [x] Importance set to `"control"` with a distinct color.
    *   [x] Message text displays payload directly.
*   [x] **`debug-layout` Command:**
    *   [x] Toggle layout debugging (`"enable"`/`"disable"` payload).
    *   [x] Visual feedback: Green bounding boxes for UI elements, pink for message columns, blue for message wrap line.
*   [x] **`log-control` Command:**
    *   [x] Toggle logging of control messages to the main display (`"enable"`/`"disable"` payload).

## Phase 4: Sticky Messages
*   [ ] **Message Importance Handling:**
    *   [x] Ensure JSON messages can include an `importance` field ("info", "warning", "error"). (Implemented in `Message` dataclass and parsing)
    *   [x] Store this importance level with each message object. (Implemented)
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

## Phase 7: Button Functionality & Advanced Features (New)
*   [ ] **Implement "CLEAR" Button Logic:**
    *   [ ] On touch (or MQTT command), clear all messages from `messages_store` (including future sticky messages).
    *   [ ] Re-render the display.
*   [ ] **Implement "RELATIVE" Button Logic:**
    *   [ ] Add a state variable to toggle between absolute and relative timestamps.
    *   [ ] Modify message rendering to display timestamps as "HH:MM:SS" (absolute) or "-HH:MM:SS ago" (relative).
    *   [ ] Update button visual state if possible (e.g., highlight).
*   [ ] **Implement "CLOCK" Button Logic:**
    *   [ ] Add a global state variable to switch between "event log" mode and "clock" mode.
    *   [ ] Design and implement a full-screen LCARS-style clock display function.
    *   [ ] Modify main loop/render logic to show the clock when in "clock" mode.
    *   [ ] The "CLOCK" button (or another mechanism) should allow switching back to the event log.

## Post-Implementation
*   [ ] **Documentation Update:**
    *   [ ] Update `README.org` with new features, configuration, and setup.
    *   [ ] Update `mqtt_alert_panel.env.example` (e.g. for `DISPLAY_ROTATE`).
*   [ ] **Code Cleanup & Refinement:**
    *   [ ] Review for performance, especially on RPi 2.
    *   [ ] Refactor for clarity and maintainability.
*   [ ] **Update `AI.md`:**
    *   [ ] Mark completed phases in `PLAN.md`.
    *   [ ] Update project structure if it evolves.
