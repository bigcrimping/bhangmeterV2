# Nuclear Event Detector - bhangmeterV2

<div align="center">
  <img src="https://github.com/user-attachments/assets/c01477d0-82af-4875-ba32-bf114a4e8395" alt="Untitled-1">
</div>

The BhangmeterV2 is a RaspberryPiPico2W powered device which detects the gamma ray burst from a nuclear explosion and uploads the details into a JSON.

On start-up all three lights flash until WiFi is connected.
Every minute the JSON is updated with the latest status of the device.
On detection of a nuclear event the JSON is updated and timestamp added, the red indicator is then lit.

The latest status can be found at [www.hasanukegoneoff.com](https://www.hasanukegoneoff.com)

# Software Setup

To setup the Raspberry Pi, load MicroPython from https://micropython.org/download/

Once loaded, put the `main.py` and `secrets.py` into the MicroPython environment.

You will need to update the `secrets.py` file with your WiFi details, your GitHub token, and the path to the repo where the `.json` is stored.

# Mechanical Build

<div align="center">
  <img src="https://github.com/user-attachments/assets/79fe3f5b-c295-4410-a7aa-454044795b2e" alt="Build_Instructions_bh">
</div>

# PCB Build

The PCB is a simple double-sided board. The Gerbers are in the relevant folder and should be easy to produce by any PCB vendor.

<div align="center">
  <img src="https://github.com/user-attachments/assets/6a45c632-b0fe-4354-8b7f-7c28b8e98fa8" alt="pcb_top">
</div>


<div align="center">
  <img src="https://github.com/user-attachments/assets/d13b05cb-b5cc-4c9b-bd02-011d11860dd1" alt="pcb_bot">
</div>

# BIST (Built in self test)

As it is largely impractical to set off a weapon to test the device is functionality the BIST pin of the HSN-1000L can be asserted to trigger the NED pin and confirm the device is working OK.

The SW1 switch triggers this functionality, on successful test the BIST button illuminates green

# How does it work?

The Bhangmeter V2 employs an HSN-1000L Nuclear Event Detector to register the initial gamma ray burst from a nuclear explosion. This burst travels at the speed of light and reaches the detector almost instantly. It is followed shortly by the neutron flux—traveling at roughly 10% the speed of light—and then the blast wave, which moves much slower at Mach 1.5 to 3, arriving several milliseconds to seconds later depending on the distance.

<div align="center">
  <img src="https://github.com/user-attachments/assets/2bece322-5ea8-42a5-8049-cbf15bcab559" alt="blast_to_diode" height="200px">
</div>

The HSN-1000L detects the gamma burst and outputs an active-low pulse, which the microcontroller interprets as a "Nuclear Event Detection" (NED). This triggers a routine that logs the exact time of the event.

<div align="center">
  <img src="https://github.com/user-attachments/assets/aab75a1a-f552-4dfd-8801-7d6a44f75b4a" alt="computer" height="200px">
</div>

Once detected by the onboard computer, the NED timestamp is uploaded to the cloud for permanent storage.

<div align="center">
  <img src="https://github.com/user-attachments/assets/db108309-35af-473e-91ee-56fc62db3a8e" alt="cloud" height="200px">
</div>

A short time later—depending on the distance from the detonation site—the blast wave reaches the Bhangmeter V2, marking the completion of its mission. Its specialized polymer casing provides brief ablative cooling upon impact.

<div align="center">
  <img src="https://github.com/user-attachments/assets/f742e814-d996-41aa-b983-b5ae7cac90e1" alt="destruct" height="200px">
</div>


