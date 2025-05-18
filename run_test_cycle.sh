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
MQTT_DATA_TOPIC_PREFIX_ON_RPI="home/alert/"
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

    # Construct the command to be run on the RPi
    # Note: MQTT_BROKER_HOST is expanded locally.
    # User/password are intentionally omitted; mosquitto_pub on RPi must handle auth.
    local remote_command="mosquitto_pub -h '$MQTT_BROKER_HOST' -t '$full_topic' -m '$message_payload'"

    if ! ssh "$RPI_USER@$RPI_HOST" "$remote_command"; then
        echo "FAILURE: Failed to send MQTT command via RPi."
        exit 1
    fi
}

# Sends a data message (JSON payload) via MQTT by executing mosquitto_pub on the RPi.
# Arguments:
#   $1: Topic suffix (e.g., "test_messages")
#   $2: JSON message payload string
send_lcars_data_message_on_rpi() {
    local topic_suffix="$1"
    local json_payload="$2"
    local full_topic="${MQTT_DATA_TOPIC_PREFIX_ON_RPI}${topic_suffix}"

    # Construct the command to be run on the RPi
    local remote_command="mosquitto_pub -h '$MQTT_BROKER_HOST' -t '$full_topic' -m '$json_payload'"

    if ! ssh "$RPI_USER@$RPI_HOST" "$remote_command"; then
        echo "FAILURE: Failed to send MQTT data message via RPi."
        exit 1
    fi
}

# Checks journalctl logs on the RPi for tracebacks for the current service invocation.
check_rpi_logs() {
    # No longer takes a timestamp argument
    local log_check_command
    local invocation_id_command
    local invocation_id
    local display_log_command

    # Give a moment for logs to be written after a restart/event
    sleep 3

    invocation_id_command="systemctl show -p InvocationID --value $SERVICE_NAME"
    # Capture the InvocationID from the RPi
    invocation_id=$(ssh "$RPI_USER@$RPI_HOST" "$invocation_id_command")

    if [ -z "$invocation_id" ]; then
        echo "FAILURE: Could not retrieve InvocationID for $SERVICE_NAME."
        echo "This might indicate the service is not running or failed to start properly."
        echo "--- Last 50 log lines for $SERVICE_NAME as a fallback ---"
        ssh "$RPI_USER@$RPI_HOST" "sudo journalctl -u $SERVICE_NAME -n 50 --no-pager -o cat"
        echo "-----------------------------------------------------"
        exit 1
    fi

    # Command to check for tracebacks for the current invocation.
    # Using -i for case-insensitive "Traceback"
    log_check_command="sudo journalctl _SYSTEMD_INVOCATION_ID='$invocation_id' -o cat | grep -q -i 'Traceback (most recent call last):'"

    if ssh "$RPI_USER@$RPI_HOST" "$log_check_command"; then
        echo "FAILURE: Traceback detected in $SERVICE_NAME logs for InvocationID $invocation_id."
        echo "--- Displaying up to 100 lines from $SERVICE_NAME for InvocationID $invocation_id ---"
        # Using --lines=100 and --no-pager for cleaner output. -o cat ensures raw text.
        display_log_command="sudo journalctl _SYSTEMD_INVOCATION_ID='$invocation_id' --no-pager --lines=100 -o cat"
        ssh "$RPI_USER@$RPI_HOST" "$display_log_command"
        echo "-----------------------------------------------------"
        exit 1
    fi
}

# --- Main Script ---

echo "[TEST SCRIPT] Starting test cycle..."

# 1. Git Push
echo "[TEST SCRIPT] Step 1: Pushing local changes to remote repository..."
git push -q

# 2. SSH to RPi, Pull, Restart Service
echo "[TEST SCRIPT] Step 2: Updating code on RPi and restarting $SERVICE_NAME..."
ssh "$RPI_USER@$RPI_HOST" "cd $RPI_PROJECT_DIR && git pull --ff-only -q && sudo systemctl restart $SERVICE_NAME > /dev/null"

# 3. Check logs after first restart
echo "[TEST SCRIPT] Step 3: Checking logs after initial service restart..."
check_rpi_logs

# 3.1 Send test messages with different importance levels
echo "[TEST SCRIPT] Step 3.1: Sending test messages with different importance levels..."
send_lcars_data_message_on_rpi "test/info"     '{"message": "Test INFO message from script", "source": "TestScript", "importance": "info"}'
send_lcars_data_message_on_rpi "test/warning"  '{"message": "Test WARNING message from script", "source": "TestScript", "importance": "warning"}'
send_lcars_data_message_on_rpi "test/error"    '{"message": "Test ERROR message from script", "source": "TestScript", "importance": "error"}'

# 4. Send MQTT message via RPi to switch to 'clock' mode
echo "[TEST SCRIPT] Step 4: Sending MQTT message via RPi to switch to 'clock' mode..."
echo "[TEST SCRIPT] Waiting 1 second before sending clock mode command..."
sleep 1
send_lcars_command_on_rpi "mode-select" "clock"

# 5. Check logs after MQTT messages and mode switch command
echo "[TEST SCRIPT] Step 5: Checking logs after sending test messages and mode switch command..."
check_rpi_logs

# 6. Restart service again (to test shutdown/startup sequence)
echo "[TEST SCRIPT] Step 6: Restarting $SERVICE_NAME again on RPi..."
ssh "$RPI_USER@$RPI_HOST" "sudo systemctl restart $SERVICE_NAME"

# 7. Check logs after second restart
echo "[TEST SCRIPT] Step 7: Checking logs after second service restart..."
check_rpi_logs

echo "[TEST SCRIPT] All checks passed. Test cycle successful."
exit 0
