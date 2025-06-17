"""
BhangMeter V2 - Nuclear Event Detection System
This script monitors for nuclear events and uploads data to GitHub.
It handles NED (Nuclear Event Detection) interrupts and periodic status updates.
"""

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
NED_EVENT = 0  # Nuclear Event Detection Flag
BIST_ENABLED = False  # BIST flag

#######################
# Network Configuration
#######################

NTP_SERVER = "pool.ntp.org"  # NTP server for time synchronization

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
    
    Triggered on falling edge of NED_OUT. Records event time and
    initiates data upload to GitHub.
    
    Args:
        pin: The pin that triggered the interrupt
    """
    global NED_EVENT
    NED_OUT.irq(handler=None)  # Disable interrupts during handling
    BIST_EN.irq(handler=None)
    
    NED_EVENT = 1  # Set nuclear event flag
    LED_R.on()     # Visual indication of nuclear event
    
    # Record and upload event data
    ned_timestamp = get_timestamp()
    upload_to_github(ned_timestamp)
    print("NED event recorded and uploaded")
    
    # Re-enable interrupts
    NED_OUT.irq(trigger=machine.Pin.IRQ_RISING, handler=ned_interrupt_handler)
    BIST_EN.irq(trigger=machine.Pin.IRQ_RISING, handler=bist_interrupt_handler)

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
    start_time = time.time()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(secrets.SSID, secrets.PASSWORD)
    
    while not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        # Visual connection attempt indication
        for led in [LED_W, LED_R, LED_G]:
            led.on()
        time.sleep(0.5)
        for led in [LED_W, LED_R, LED_G]:
            led.off()
        time.sleep(0.5)
        
        if time.time() - start_time > timeout:
            print("Failed to connect to Wi-Fi. Restarting...")
            LED_R.on()  # Error indication
            LED_G.off()
            LED_W.off()
            machine.reset()
    
    print("Connected to Wi-Fi")
    LED_W.on()  # Connection success indication
    return True

def get_ntp_time(retries=3):
    """Get current time from NTP server.
    
    Args:
        retries: Number of attempts to get NTP time
    
    Returns:
        tuple: Time tuple (year, month, day, hour, minute, second, ...)
    """
    NTP_DELTA = 2208988800
    for attempt in range(retries):
        try:
            addr = socket.getaddrinfo(NTP_SERVER, 123)[0][-1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            
            ntp_query = b'\x1b' + 47 * b'\0'
            sock.sendto(ntp_query, addr)
            msg, _ = sock.recvfrom(48)
            sock.close()

            ntp_time = struct.unpack("!I", msg[40:44])[0] - NTP_DELTA
            return time.localtime(ntp_time)
            
        except Exception as e:
            print(f"Attempt {attempt + 1} failed to get network time: {e}")
            time.sleep(2)
    
    print("Failed to get network time after retries, using device time.")
    return time.localtime()

#######################
# GitHub Data Management
#######################

def upload_to_github(ned_time=None):
    """Upload current status and event data to GitHub.
    
    Args:
        ned_time: Timestamp of nuclear event detection, if any
    """
    global NED_EVENT
    try:
        sha, existing_data = get_file_data()

        # Update data from existing file 
        total_count = existing_data.get("total minutes monitored", 0) + 1
        nuke_status = existing_data.get("nuke gone off?", "no")
        
        # Update nuke status if event detected
        if NED_EVENT == 1 or nuke_status == "yes":
            nuke_status = "yes"

        # Get current timestamp once to use in multiple places
        current_time = get_timestamp()

        # Prepare new data payload
        new_data = {
            "station": secrets.STATION,
            "nuke gone off?": nuke_status,
            "last monitor upload date": current_time,
            "nuke detected time": ned_time,
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
        response = urequests.request("PUT", url, headers=headers, data=json.dumps(data))
        try:
            if response.status_code in [200, 201]:
                print("File uploaded successfully")
            else:
                print(f"Failed to upload file: {response.status_code}")
        finally:
            response.close()
            
    except Exception as e:
        print(f"Error in upload_to_github: {e}")
        LED_R.on()  # Error indication
        time.sleep(1)
        LED_R.off()

def get_file_data():
    """Retrieve existing data file from GitHub.
    
    Returns:
        tuple: (sha, json_data) or (None, None) if file doesn't exist
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
            encoded_content = file_data['content']
            
            # Decode content from base64
            decoded_content = ubinascii.a2b_base64(encoded_content).decode()
            json_data = json.loads(decoded_content)
            return sha, json_data
            
        elif response.status_code == 404:
            print(f"File does not exist, creating new: {secrets.FILE_PATH}")
            return None, None
            
        else:
            print(f"Failed to check file: {response.status_code}")
            return None, None
            
    except ValueError as e:
        print(f"Error parsing JSON response: {e}")
        return None, None
        
    finally:
        response.close()

def get_timestamp():
    """Get formatted timestamp string.
    
    Returns:
        str: Formatted timestamp (YYYY-MM-DD HH:MM:SS)
    """
    tm = get_ntp_time()
    return f"{tm[0]}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}"

#######################
# Main Program
#######################

def main():
    """Main program loop."""
    # Initialize LED states
    LED_W.off()
    LED_R.off()
    LED_G.off()
    BIST_OUT.on() 
    retry_count = 0
    max_retries = 3
    global BIST_ENABLED
    print("NED_OUT: ", NED_OUT.value())
    # Main program loop with retry mechanism
    while retry_count < max_retries:
        try:
            if connect_wifi():
                LED_W.on()  # Connected to WiFi
                # Initialize interrupt handlers
                BIST_EN.irq(trigger=machine.Pin.IRQ_RISING, handler=bist_interrupt_handler)
                NED_OUT.irq(trigger=machine.Pin.IRQ_RISING, handler=ned_interrupt_handler)
                last_upload_time = time.time() - 60  # Force immediate upload on first run
                while True:
                    try:
                        # Check for BIST flag
                        if BIST_ENABLED:
                            NED_OUT.irq(handler=None)
                            print("in")
                            # Run BIST sequence (all logic moved from handler)
                            start_time = time.time()
                            #print("NED_OUT: ", NED_OUT.value())
                            BIST_OUT.off()  # Start BIST sequence
                            BIST_OUT.on()   # Only short pulse is required to activate NED BIST
                            #print("NED_OUT: ", NED_OUT.value())
                            # Wait up to 1 second for NED_OUT response
                            while time.time() - start_time < 1:
                                if NED_OUT.value() == 1:
                                    print("BIST Passed")
                                    LED_G.on()  # Visual indication of BIST success
                                    time.sleep(2)
                                    LED_G.off()
                                    LED_R.off() # Also turn off RED as manual reset of proper NED event.
                                    break

                            BIST_OUT.on()  # Reset BIST output
                            
                            BIST_ENABLED = False  # Reset flag
                        
                        # Timer-based upload
                        current_time = time.time()
                        if current_time - last_upload_time >= 60:
                            upload_to_github()
                            last_upload_time = current_time
                        time.sleep(0.1)  # Short sleep for responsiveness
                    except Exception as e:
                        print(f"Error in main loop: {e}")
                        time.sleep(5)  # Brief delay before retry
            else:
                print("Failed to connect to WiFi")
                retry_count += 1
        except Exception as e:
            print(f"Critical error: {e}")
            retry_count += 1
            time.sleep(5)
    
    # Reset device if max retries exceeded
    print("Maximum retries reached, resetting device...")
    LED_R.on()  # Error indication
    LED_G.off()
    LED_W.off()
    machine.reset()



# Start program
if __name__ == "__main__":
    main()

