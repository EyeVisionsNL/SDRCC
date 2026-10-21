# 🔧 Install SDRCC

**Requirements:** Ubuntu Linux x86-64, internet access and suitable RTL-SDR hardware. A Raspberry Pi is not the reference platform for full SDRCC.

## 1. Install

Open a terminal as your normal Ubuntu user:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone --depth 1 --branch main https://github.com/EyeVisionsNL/SDRCC.git ~/SDRCC
cd ~/SDRCC
./install.sh
```

Do **not** use `sudo ./install.sh`: the installer asks for permissions when needed.

## 2. Configure

Enter your station name, coordinates and altitude. Follow the AIS-catcher prompts. Receivers can be connected and assigned later.

## 3. Open the dashboard

Visit `http://localhost:8080` on the SDRCC computer, or use its IP address on your trusted network. Open **System**.

![SDRCC System dashboard](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/system.webp)

**AIS setup later?** Stop active missions and Radio Receiver, then run `~/SDRCC/install.sh --ais-setup`. For existing stations, update with **System → Advanced Maintenance**.

Next: [[First steps]].
