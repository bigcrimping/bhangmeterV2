"""
BhangMeter V2 - Nuclear Event Detection System
This script monitors for nuclear events and uploads data to GitHub.
It handles NED (Nuclear Event Detection) interrupts and periodic status updates.
"""

import gc
import json
import machine  # For device reset
import network
import secrets  # Import Wi-Fi and GitHub credentials, device paramaters
import socket
import struct
import time
import ubinascii
import urequests

#######################
# Hardware Configuration
#######################

# LED Indicators
LED_W = machine.Pin(2, machine.Pin.OUT)  # White LED - WiFi Status
LED_G = machine.Pin(6, machine.Pin.OUT)  # Green LED - BIST Status
LED_R = machine.Pin(11, machine.Pin.OUT) # Red LED - Error/NED Status

# Input/Output Pins
BIST_EN = machine.Pin(12, machine.Pin.IN)   # BIST Enable Input
NED_OUT = machine.Pin(18, machine.Pin.IN)   # Nuclear Event Detection Input
BIST_OUT = machine.Pin(14, machine.Pin.OUT) # BIST Output Signal

# Initialize Hardware States
BIST_OUT.on()
NED_TICKS = None      # ticks_ms() of an NED event not yet picked up by the main loop
NED_LATCHED = False   # Red LED latched on by an NED event (cleared by a BIST pass)
BIST_ENABLED = False  # BIST requested flag
BIST_RUNNING = False  # True while the BIST sequence is pulsing the detector

#######################
# Network Configuration
#######################

NTP_SERVER = "pool.ntp.org"  # NTP server for time synchronization
UPLOAD_INTERVAL_MS = 60 * 1000         # Periodic status upload
NED_RETRY_INTERVAL_MS = 10 * 1000      # Retry delay for a failed NED upload
TIME_SYNC_INTERVAL_MS = 60 * 60 * 1000 # Re-sync the clock from NTP
TIME_SYNC_RETRY_MS = 60 * 1000         # Retry delay while the clock is not set

TIME_SYNCED = False  # True once the RTC has been set from NTP

#######################
# Interrupt Handlers
#######################

def bist_interrupt_handler(pin):
    """Built-In Self Test (BIST) interrupt handler.
    Args:
        pin: The pin that triggered the interrupt
    """
    global BIST_ENABLED
    BIST_ENABLED = True

def ned_interrupt_handler(pin):
    """Nuclear Event Detection (NED) interrupt handler.

    Triggered on the rising edge of NED_OUT (the detector's active-low
    pulse is inverted by the buffer). Only records when the event
    happened; the main loop does the upload, so no network I/O runs
    in interrupt context.

    Args:
        pin: The pin that triggered the interrupt
    """
    global NED_TICKS, NED_LATCHED
    if BIST_RUNNING:
        return  # Pulse caused by the self test, not a real event

    if NED_TICKS is None:
        NED_TICKS = time.ticks_ms()  # Keep the earliest unhandled event
    NED_LATCHED = True
    LED_R.on()  # Visual indication of nuclear event

#######################
# Network Functions
#######################

def connect_wifi(timeout=10):
    """Establish WiFi connection with timeout.

    Args:
        timeout: Maximum time to attempt connection in seconds

    Returns:
        bool: True if connection successful, False otherwise
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        try:
            wlan.disconnect()  # Clear any stale connection attempt
        except OSError:
            pass
        wlan.connect(secrets.SSID, secrets.PASSWORD)

    start = time.ticks_ms()
    connected = True
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout * 1000:
            connected = False
            break
        print("Connecting to Wi-Fi...")
        # Visual connection attempt indication
        for led in [LED_W, LED_R, LED_G]:
            led.on()
        time.sleep(0.5)
        for led in [LED_W, LED_R, LED_G]:
            led.off()
        time.sleep(0.5)

    # Restore indicators: the flashing must not hide a latched NED event
    LED_G.off()
    LED_R.value(1 if NED_LATCHED else 0)
    LED_W.value(1 if connected else 0)
    print("Connected to Wi-Fi" if connected else "Failed to connect to Wi-Fi")
    return connected

def sync_time(retries=3):
    """Set the device clock (UTC) from an NTP server.

    Args:
        retries: Number of attempts to get NTP time

    Returns:
        bool: True if the clock was set, False otherwise
    """
    global TIME_SYNCED
    NTP_DELTA = 2208988800
    for attempt in range(retries):
        sock = None
        try:
            addr = socket.getaddrinfo(NTP_SERVER, 123)[0][-1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)

            ntp_query = b'\x1b' + 47 * b'\0'
            sock.sendto(ntp_query, addr)
            msg, _ = sock.recvfrom(48)

            ntp_time = struct.unpack("!I", msg[40:44])[0] - NTP_DELTA
            tm = time.gmtime(ntp_time)
            # RTC tuple: (year, month, day, weekday, hour, minute, second, subseconds)
            machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
            TIME_SYNCED = True
            return True

        except Exception as e:
            print(f"Attempt {attempt + 1} failed to get network time: {e}")
            time.sleep(2)

        finally:
            if sock:
                sock.close()

    print("Failed to get network time after retries.")
    return False

def get_timestamp(epoch=None):
    """Get formatted timestamp string from the device clock.

    Args:
        epoch: Seconds since the epoch to format, or None for now

    Returns:
        str: Formatted timestamp (YYYY-MM-DD HH:MM:SS), UTC
    """
    tm = time.gmtime(time.time() if epoch is None else epoch)
    return f"{tm[0]}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}"

#######################
# GitHub Data Management
#######################

def upload_to_github(ned_time=None):
    """Upload current status and event data to GitHub.

    Args:
        ned_time: Timestamp of nuclear event detection, if any

    Returns:
        bool: True if the file was written, False otherwise
    """
    try:
        gc.collect()  # TLS needs a large contiguous block of heap
        sha, existing_data = get_file_data()

        # Update data from existing file
        total_count = existing_data.get("total minutes monitored", 0)
        nuke_status = existing_data.get("nuke gone off?", "no")
        nuke_time = existing_data.get("nuke detected time")

        if ned_time is None:
            total_count += 1  # Periodic upload: one more minute monitored
        else:
            nuke_status = "yes"
            nuke_time = ned_time

        current_time = get_timestamp()

        # Prepare new data payload
        new_data = {
            "station": secrets.STATION,
            "nuke gone off?": nuke_status,
            "last monitor upload date": current_time,
            "nuke detected time": nuke_time,
            "total minutes monitored": total_count,
            "lat": secrets.LAT,
            "long": secrets.LONG
        }

        # Convert JSON data to string and encode in base64 using ubinascii
        json_string = json.dumps(new_data)
        encoded_content = ubinascii.b2a_base64(json_string.encode()).decode().strip()

        # GitHub API URL for uploading files
        url = f"https://api.github.com/repos/{secrets.GITHUB_USER}/{secrets.REPO_NAME}/contents/{secrets.FILE_PATH}"

        # Prepare headers for the GitHub API request
        headers = {
            "Authorization": f"token {secrets.GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"BhangmeterV2.{secrets.STATION}"
        }

        # Prepare data for the GitHub API request
        data = {
            "message": f"Update from {secrets.STATION} at {current_time}",
            "content": encoded_content,
            "branch": "main",
        }

        # If the file exists, include the SHA to update it
        if sha:
            data["sha"] = sha

        # Send update to GitHub
        gc.collect()
        response = urequests.request("PUT", url, headers=headers, data=json.dumps(data))
        try:
            if response.status_code in [200, 201]:
                print("File uploaded successfully")
                return True
            print(f"Failed to upload file: {response.status_code}")
        finally:
            response.close()

    except Exception as e:
        print(f"Error in upload_to_github: {e}")

    # Error indication (leave the LED on if it is latched by an NED event)
    LED_R.on()
    time.sleep(1)
    if not NED_LATCHED:
        LED_R.off()
    return False

def get_file_data():
    """Retrieve existing data file from GitHub.

    Returns:
        tuple: (sha, json_data), or (None, {}) if the file doesn't exist yet

    Raises:
        RuntimeError: GitHub returned anything other than 200 or 404, so
            the existing data is unknown and must not be overwritten
    """
    url = f"https://api.github.com/repos/{secrets.GITHUB_USER}/{secrets.REPO_NAME}/contents/{secrets.FILE_PATH}"
    headers = {
        "Authorization": f"token {secrets.GITHUB_TOKEN}",
        "User-Agent": f"BhangmeterV2.{secrets.STATION}"
    }

    response = urequests.get(url, headers=headers)
    print("Response Status Code:", response.status_code)

    try:
        if response.status_code == 200:
            file_data = response.json()
            sha = file_data['sha']

            # Decode content from base64
            decoded_content = ubinascii.a2b_base64(file_data['content']).decode()
            try:
                json_data = json.loads(decoded_content)
            except ValueError as e:
                print(f"Existing file is not valid JSON, replacing it: {e}")
                json_data = {}
            if not isinstance(json_data, dict):
                json_data = {}
            return sha, json_data

        elif response.status_code == 404:
            print(f"File does not exist, creating new: {secrets.FILE_PATH}")
            return None, {}

        raise RuntimeError(f"Failed to check file: {response.status_code}")

    finally:
        response.close()

#######################
# BIST
#######################

def run_bist():
    """Pulse the detector's BIT input and check that NED_OUT responds."""
    global BIST_ENABLED, BIST_RUNNING, NED_LATCHED
    BIST_RUNNING = True  # NED handler ignores the test pulse
    passed = False
    try:
        start = time.ticks_ms()
        BIST_OUT.off()  # Start BIST sequence
        BIST_OUT.on()   # Only short pulse is required to activate NED BIST

        # Wait up to 1 second for NED_OUT response
        while time.ticks_diff(time.ticks_ms(), start) < 1000:
            if NED_OUT.value() == 1:
                passed = True
                break

        if passed:
            print("BIST Passed")
            NED_LATCHED = False
            LED_R.off()  # Also turn off RED as manual reset of proper NED event.
            LED_G.on()   # Visual indication of BIST success
            time.sleep(2)
            LED_G.off()
        else:
            print("BIST Failed")
            for _ in range(5):  # Visual indication of BIST failure
                LED_R.on()
                time.sleep(0.2)
                LED_R.off()
                time.sleep(0.2)
            LED_R.value(1 if NED_LATCHED else 0)
    finally:
        BIST_OUT.on()  # Reset BIST output
        BIST_RUNNING = False
        # Wait for the button to be let go (up to 5 s) so a long press or
        # release bounce does not start a second test
        release_start = time.ticks_ms()
        while BIST_EN.value() == 0 and time.ticks_diff(time.ticks_ms(), release_start) < 5000:
            time.sleep(0.01)
        time.sleep(0.05)
        BIST_ENABLED = False  # Reset flag (also discards switch bounce)

#######################
# Main Program
#######################

def main():
    """Main program loop."""
    global NED_TICKS

    # Initialize LED states
    LED_W.off()
    LED_R.off()
    LED_G.off()
    BIST_OUT.on()
    print("NED_OUT: ", NED_OUT.value())

    # Arm the detector first so an event during start-up is not missed
    NED_OUT.irq(trigger=machine.Pin.IRQ_RISING, handler=ned_interrupt_handler)
    # SW1 pulls BIST_EN low when pressed, so the falling edge is the press
    BIST_EN.irq(trigger=machine.Pin.IRQ_FALLING, handler=bist_interrupt_handler)

    wlan = network.WLAN(network.STA_IF)
    if not connect_wifi() and NED_TICKS is None:
        print("Restarting...")
        LED_R.on()  # Error indication
        machine.reset()

    sync_time()
    now = time.ticks_ms()
    last_time_sync = now
    last_upload = time.ticks_add(now, -UPLOAD_INTERVAL_MS)  # Force immediate upload on first run
    last_ned_try = time.ticks_add(now, -NED_RETRY_INTERVAL_MS)
    pending_ned_time = None  # Event timestamp waiting to be uploaded

    while True:
        try:
            # Check for BIST flag
            if BIST_ENABLED:
                run_bist()

            # Reconnect if the WiFi has dropped
            if not wlan.isconnected():
                connect_wifi()

            now = time.ticks_ms()

            # Keep the clock in step with NTP
            sync_interval = TIME_SYNC_INTERVAL_MS if TIME_SYNCED else TIME_SYNC_RETRY_MS
            if wlan.isconnected() and time.ticks_diff(now, last_time_sync) >= sync_interval:
                sync_time(retries=1)
                last_time_sync = now

            # Pick up an event flagged by the interrupt handler
            if NED_TICKS is not None:
                if not TIME_SYNCED and wlan.isconnected():
                    sync_time(retries=1)
                age = time.ticks_diff(time.ticks_ms(), NED_TICKS) // 1000
                event_time = get_timestamp(time.time() - age)
                NED_TICKS = None
                if pending_ned_time is None:
                    pending_ned_time = event_time
                    last_ned_try = time.ticks_add(now, -NED_RETRY_INTERVAL_MS)
                print("NED event at", event_time)

            # Upload a detected event, retrying until it gets through
            if pending_ned_time and time.ticks_diff(now, last_ned_try) >= NED_RETRY_INTERVAL_MS:
                last_ned_try = now
                if upload_to_github(pending_ned_time):
                    print("NED event recorded and uploaded")
                    pending_ned_time = None

            # Timer-based upload
            elif time.ticks_diff(now, last_upload) >= UPLOAD_INTERVAL_MS:
                last_upload = now
                upload_to_github()

            time.sleep(0.1)  # Short sleep for responsiveness
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)  # Brief delay before retry


# Start program
if __name__ == "__main__":
    main()
