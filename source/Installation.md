# 🔧 Install SDRCC

## Before you start

Use an **Ubuntu Linux x86-64 computer** with an internet connection for installation. Ubuntu Desktop is the main development and test environment; Ubuntu Server can also be used with a remote browser. The full SDRCC workload is intended for an x86-64 PC. Raspberry Pi is not the reference platform for this project.

Connect suitable RTL-SDR receivers and antennas for the signals you want to receive. Hardware bindings can also be configured after installation.

## 1. Open Terminal

For a fresh installation, run:


```bash
sudo apt-get update
sudo apt-get install -y git
git clone --depth 1 --branch main https://github.com/EyeVisionsNL/SDRCC.git ~/SDRCC
cd ~/SDRCC
./install.sh
```

Run **./install.sh as your normal Ubuntu user**. The installer requests elevated privileges when needed.

## 2. Complete the installer

Enter the station name, location, latitude, longitude and altitude when asked. Use your own station values: satellite pass calculations depend on them. Follow the AIS-catcher setup prompts, or defer receiver configuration until the hardware is connected.

## 3. Open the dashboard

On the SDRCC computer, open **http://localhost:8080**. From another computer on the same trusted network, replace localhost with the SDRCC computer's IP address, for example **http://192.168.1.50:8080**. This address is an example.

Open **System** and continue with [[First steps]].

![System dashboard](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/system.webp)

## Set up AIS later

Stop active missions and Radio Receiver sessions, then run:


```bash
cd ~/SDRCC
./install.sh --ais-setup
```

## Already installed?

Use **System → Advanced Maintenance** for managed updates. See [[Updates and troubleshooting]].

[[Home]] · Next: [[First steps]]
