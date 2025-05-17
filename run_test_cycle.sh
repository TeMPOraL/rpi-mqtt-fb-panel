#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
RPI_USER="temporal"
RPI_HOST="192.168.88.111"
RPI_PROJECT_DIR="~/repos/rpi-mqtt-fb-panel"
SERVICE_NAME="mqtt-alert.service"

MQTT_BROKER_HOST="homeassistant.local"
# This is the prefix for data topics on the RPi, where test messages will be sent.
MQTT_DATA_TOPIC_PREFIX_ON_RPI="home/lcars_panel/"
# This is the prefix for control topics on the RPi. Commands like 'mode-select' will be appended.
MQTT_CONTROL_TOPIC_PREFIX_ON_RPI="lcars/alert-panel/"


# --- Helper Functions ---
# Sends a command via MQTT by executing mosquitto_pub on the RPi.
# Assumes mosquitto_pub on the RPi is configured to authenticate if needed
# (e.g., via a config file or environment variables accessible to the RPI_USER).
# Arguments:
#   $1: Topic suffix (e.g., "mode-select")
#   $2: Message payload (e.g., "clock")
send_lcars_command_on_rpi() {
    local topic_suffix="$1"
    local message_payload="$2"
    local full_topic="${MQTT_CONTROL_TOPIC_PREFIX_ON_RPI}${topic_suffix}"

    echo "Sending MQTT command via RPi: Topic='$full_topic', Message='$message_payload'"
    # Construct the command to be run on the RPi
    # Note: MQTT_BROKER_HOST is expanded locally.
    # User/password are intentionally omitted; mosquitto_pub on RPi must handle auth.
    local remote_command="mosquitto_pub -h '$MQTT_BROKER_HOST' -t '$full_topic' -m '$message_payload'"

    if ! ssh "$RPI_USER@$RPI_HOST" "$remote_command"; then
        echo "FAILURE: Failed to send MQTT command via RPi."
        exit 1
    fi
    echo "MQTT command sent successfully via RPi."
}

# Sends a data message (JSON payload) via MQTT by executing mosquitto_pub on the RPi.
# Arguments:
#   $1: Topic suffix (e.g., "test_messages")
#   $2: JSON message payload string
send_lcars_data_message_on_rpi() {
    local topic_suffix="$1"
    local json_payload="$2"
    local full_topic="${MQTT_DATA_TOPIC_PREFIX_ON_RPI}${topic_suffix}"

    echo "Sending MQTT data message via RPi: Topic='$full_topic', Message='$json_payload'"
    # Construct the command to be run on the RPi
    local remote_command="mosquitto_pub -h '$MQTT_BROKER_HOST' -t '$full_topic' -m '$json_payload'"

    if ! ssh "$RPI_USER@$RPI_HOST" "$remote_command"; then
        echo "FAILURE: Failed to send MQTT data message via RPi."
        exit 1
    fi
    echo "MQTT data message sent successfully via RPi."
}

# Checks journalctl logs on the RPi for tracebacks since a given timestamp.
# Arguments:
#   $1: Timestamp string (YYYY-MM-DD HH:MM:SS) for 'journalctl --since'
check_rpi_logs() {
    local since_timestamp="$1"
    local log_check_command

    echo "Checking $SERVICE_NAME logs on RPi since $since_timestamp UTC..."
    # Give a moment for logs to be written
    sleep 3

    # Command to check for tracebacks.
    # grep -q will be silent and exit 0 if found, 1 if not.
    log_check_command="sudo journalctl -u $SERVICE_NAME --since '$since_timestamp' -o cat | grep -q -i 'Traceback (most recent call last):'"

    if ssh "$RPI_USER@$RPI_HOST" "$log_check_command"; then
        echo "FAILURE: Traceback detected in $SERVICE_NAME logs."
        echo "--- Relevant logs from $SERVICE_NAME since $since_timestamp UTC ---"
        ssh "$RPI_USER@$RPI_HOST" "sudo journalctl -u $SERVICE_NAME --since '$since_timestamp' -o cat"
        echo "-----------------------------------------------------"
        exit 1
    else
        echo "No traceback detected in $SERVICE_NAME logs for this step."
    fi
}

# --- Main Script ---

echo "[TEST SCRIPT] Starting test cycle..."

# 1. Git Push
echo "[TEST SCRIPT] Step 1: Pushing local changes to remote repository..."
git push
echo "[TEST SCRIPT] Git push completed."

# 2. SSH to RPi, Pull, Restart Service
echo "[TEST SCRIPT] Step 2: Updating code on RPi and restarting $SERVICE_NAME..."
# Get current UTC time on RPi *before* the service restart
current_rpi_time_utc_step2=$(ssh "$RPI_USER@$RPI_HOST" "date -u +'%Y-%m-%d %H:%M:%S'")
ssh "$RPI_USER@$RPI_HOST" "cd $RPI_PROJECT_DIR && git pull && sudo systemctl restart $SERVICE_NAME"
echo "[TEST SCRIPT] Code updated and $SERVICE_NAME restarted on RPi."

# 3. Check logs after first restart
echo "[TEST SCRIPT] Step 3: Checking logs after initial service restart..."
check_rpi_logs "$current_rpi_time_utc_step2"

# 3.1 Send test messages with different importance levels
echo "[TEST SCRIPT] Step 3.1: Sending test messages with different importance levels..."
send_lcars_data_message_on_rpi "test/info"     '{"message": "Test INFO message from script", "source": "TestScript", "importance": "info"}'
send_lcars_data_message_on_rpi "test/warning"  '{"message": "Test WARNING message from script", "source": "TestScript", "importance": "warning"}'
send_lcars_data_message_on_rpi "test/error"    '{"message": "Test ERROR message from script", "source": "TestScript", "importance": "error"}'
echo "[TEST SCRIPT] Test messages sent."

# 4. Send MQTT message via RPi to switch to 'clock' mode
echo "[TEST SCRIPT] Step 4: Sending MQTT message via RPi to switch to 'clock' mode..."
# Get current UTC time on RPi *before* the MQTT command might cause issues
current_rpi_time_utc_step4=$(ssh "$RPI_USER@$RPI_HOST" "date -u +'%Y-%m-%d %H:%M:%S'")
echo "[TEST SCRIPT] Waiting 1 second before sending clock mode command..."
sleep 1
send_lcars_command_on_rpi "mode-select" "clock"
echo "[TEST SCRIPT] MQTT message sent via RPi."

# 5. Check logs after MQTT messages and mode switch command
echo "[TEST SCRIPT] Step 5: Checking logs after sending MQTT message..."
# We use the timestamp from before the MQTT message, as the app might log immediately upon receiving it.
check_rpi_logs "$current_rpi_time_utc_step4"

# 6. Restart service again (to test shutdown/startup sequence)
echo "[TEST SCRIPT] Step 6: Restarting $SERVICE_NAME again on RPi..."
# Get current UTC time on RPi *before* the second service restart
current_rpi_time_utc_step6=$(ssh "$RPI_USER@$RPI_HOST" "date -u +'%Y-%m-%d %H:%M:%S'")
ssh "$RPI_USER@$RPI_HOST" "sudo systemctl restart $SERVICE_NAME"
echo "[TEST SCRIPT] $SERVICE_NAME restarted again on RPi."

# 7. Check logs after second restart
echo "[TEST SCRIPT] Step 7: Checking logs after second service restart..."
check_rpi_logs "$current_rpi_time_utc_step6"

echo "[TEST SCRIPT] All checks passed. Test cycle successful."
exit 0
