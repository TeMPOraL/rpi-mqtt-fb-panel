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
*   [x] **Fixed Title:** (Note: UI uses hardcoded "EVENT LOG" and "MQTT STREAM" currently, `LCARS_TITLE_TEXT` env var removed as unused).
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

## Phase 4: Multi-Mode Display Implementation (Events & Clock)
*   [x] **Phase A: Core Refactoring for Mode Management**
    *   [x] **Introduce Global Mode State:**
        *   [x] Define `current_display_mode = "events"` in `mqtt_fb_panel.py`.
    *   [x] **Refactor Main Rendering Logic:**
        *   [x] Create `refresh_display()` in `mqtt_fb_panel.py` to check `current_display_mode` and delegate to mode-specific full panel renderers.
        *   [x] Update existing render triggers to call `refresh_display()`.
    *   [x] **Generalize UI Bar Components (`lcars_ui_components.py`):**
        *   [x] Modify `render_top_bar` to accept `title_text`.
        *   [x] Modify `render_bottom_bar` to accept `label_text` and `buttons_config` list.
    *   [x] **Adapt Event Log Rendering to New Structure:**
        *   [x] Create `render_event_log_full_panel(...)` to call generalized bars and existing message list logic.
*   [x] **Phase B: Implement Clock Mode Panel**
    *   [x] **Create Clock Panel Rendering Functions:**
        *   [x] `render_clock_full_panel(...)`: Calls generalized bars (title "CURRENT TIME", timezone label, "[EVENTS]" button) and `render_clock_content_area`.
        *   [x] `render_clock_content_area(...)`: Renders large HH:MM:SS time (60% height) and YYYY-MM-DD - DayName date (40% height), centered, with dynamically sized fonts.
        *   [x] Implement timezone string generation (e.g., "Europe/Warsaw - CEST - UTC+02:00") using `datetime`, `zoneinfo`, potentially `tzlocal`.
    *   [x] **Integrate Clock Panel into Main Rendering Flow:**
        *   [x] Ensure `refresh_display()` calls `render_clock_full_panel()` for "clock" mode.
*   [x] **Phase C: Implement Mode Switching Logic**
    *   [x] **MQTT Control Command Handling (`on_mqtt`):**
        *   [x] Handle `mode-select` topic suffix with payloads `"events"` or `"clock"`.
        *   [x] Update `current_display_mode` and call `refresh_display()`.
        *   [x] Log control message to display if enabled.
    *   [x] **Button Configuration for Future Touch Input:**
        *   [x] Include unique `id` in `buttons_config` for each button (e.g., `id: 'activate_clock_mode'`).
*   [x] **Phase D: Testing and Refinement**
    *   [x] Test Event Log mode functions as before.
    *   [x] Test Clock Mode display (time, date, timezone, updates).
    *   [x] Test mode switching via MQTT.
    *   [ ] Monitor resource usage.
    *   [ ] Code review.

## Phase 5: Sticky Messages
*   [ ] **Message Importance Handling:**
    *   [x] Ensure JSON messages can include an `importance` field ("info", "warning", "error"). (Implemented in `Message` dataclass and parsing)
    *   [x] Store this importance level with each message object. (Implemented)
*   [ ] **Data Storage for Sticky Messages:**
    *   [ ] Decide on a strategy:
        *   Separate list for sticky messages.
        *   Attribute/flag on message objects in a single list.
*   [ ] **Rendering Sticky Messages (Event Log Mode):**
    *   [ ] Sticky messages ("error", "warning") are rendered in a persistent area (e.g., top of the message list).
    *   [ ] They do not scroll off screen.
    *   [ ] The space for normal rolling messages dynamically shrinks as sticky messages accumulate.
    *   [ ] Consider distinct visual styling for sticky messages (e.g., background color, icon).

## Phase 6: Clearing Mechanism
*   [x] **MQTT-based Clearing (All Event Log Messages):**
    *   [x] Define `clear-events` control command (topic suffix `clear-events` under `MQTT_CONTROL_TOPIC_PREFIX`).
    *   [x] Update `on_mqtt` to handle this command: clear `messages_store`.
    *   [x] Refresh display if in "events" mode.
*   [ ] **MQTT-based Clearing (Sticky Messages - Future):**
    *   [ ] Define a specific MQTT topic and message payload to trigger clearing of *only* sticky messages (e.g., topic `home/lcars_panel/control`, payload `{"command": "clear_sticky"}`).
    *   [ ] Update `on_mqtt` to handle this command.
    *   [ ] Implement logic to remove/clear only sticky messages from the store and re-render.

## Phase 7: Touchscreen Input (Implemented for Core Buttons)
*   [x] **Input Library Integration:**
    *   [x] Added `python-evdev` dependency (user prompted to install).
    *   [x] Implemented reading touch events from `TOUCH_DEVICE_PATH` (configurable via env var, with auto-detect fallback).
*   [x] **Event Loop Modification:**
    *   [x] `client.loop_start()` is already used.
    *   [x] Main application loop modified to poll for touch events using non-blocking `read_loop_async`.
*   [x] **Button Definition & Handling (General):**
    *   [x] `active_buttons` list stores screen coordinates and `id`s, populated during rendering.
    *   [x] Touch event dispatcher maps transformed touch coordinates (handles `DISPLAY_ROTATE` and touch device scaling) to button `id`s.
*   [x] **Touch-based Mode Switching & Clearing:**
    *   [x] When "CLEAR" button (Event Log mode) is touched, clears all messages from `messages_store`.
    *   [x] When "[CLOCK]" button (Event Log mode) is touched, switches to "clock" mode.
    *   [x] When "[EVENTS]" button (Clock mode) is touched, switches to "events" mode.
*   [ ] **Touch-based Sticky Message Clearing:** (Part of general "CLEAR" for now, specific sticky clear not implemented)
*   [ ] **Debouncing/Event Filtering:** Basic implementation (acts on `BTN_TOUCH` down event). Further refinement might be needed if issues arise.

## Phase 8: Advanced Button Functionality (Post-Touch Implementation)
*   [x] **Implement "CLEAR" Button Logic (Event Log Mode):** (Covered in Phase 7)
    *   [x] On touch, clear all messages from `messages_store` (including sticky messages).
    *   [x] Re-render the display. (Handled by `_handle_button_press` calling `refresh_display()`)
*   [ ] **Implement "RELATIVE" Button Logic (Event Log Mode):**
    *   [ ] Add a state variable to toggle between absolute and relative timestamps.
    *   [ ] Modify message rendering to display timestamps as "HH:MM:SS" (absolute) or "-HH:MM:SS ago" (relative).
    *   [ ] Update button visual state if possible (e.g., highlight).
*   [ ] **Note:** The "CLOCK" button's primary function (mode switching) is covered in Phase 7 (Touchscreen Input).

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
