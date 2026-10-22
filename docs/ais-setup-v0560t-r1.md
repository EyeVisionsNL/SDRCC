# FlexGround SDR 0.56.0t-r1 — AIS setup

The clean installer now includes AIS-catcher's own browser wizard. FlexGround
keeps its boot autostart. AIS-catcher, its legacy control service, readsb and
Traffic Voice finish the setup stage stopped and disabled at boot, ready for
FlexGround to start on demand.

## Use

On a clean machine, run `./install.sh` normally. At the AIS step, open the
address printed in the terminal, normally `http://STATION-IP:8118`. Choose one
RTL-SDR and your desired outputs, complete the password step if shown, and
use **Save & Close**. Return to the terminal and press Enter. If you have no
receiver available, enter **d** to defer; the installer explicitly reports AIS
as incomplete while the rest of FlexGround can finish installing.

On an already installed machine with this patch applied:

```bash
cd ~/SDRCC
./install.sh --ais-setup
```

This is a dedicated resume action, not the normal update path. It temporarily
stops FlexGround; active receiver reservations block it. An existing completed
managed configuration skips the wizard and retains its password, outputs and
device. Normal updates never invoke AIS setup or rewrite station settings.

At completion, `engine` is set to `on` **while AIS is stopped**, so a subsequent
FlexGround service start actually starts reception even if the wizard's
"start after saving" box was unchecked. No received AIS message is required
for configuration success; antenna coverage is a separate live check.

An existing managed service using `/etc/AIS-catcher/aiscatcher.json` retains
its command and bind address. A legacy manual service gets only the named
`90-flexground-managed.conf` drop-in. This needs an AIS-catcher binary that
advertises `-E`; unsupported older binaries fail explicitly. This patch does
not repeat the earlier unsupported `aiscatcher-install -M` invocation.
For a loopback-only listener, the terminal prints SSH tunnel instructions.

## Verification before commit

**Do not commit until the full diff has been reviewed, static/syntax and
behavior tests pass, and Marcel has run the changed installation/setup on
Ubuntu through wizard completion, service cleanup and dashboard startup.**

Local automated tests simulate systemd, the browser and hardware; they do not
prove that a particular installed AIS binary can run the wizard with a USB
receiver. The package is a test candidate until the live checks below pass.

```bash
git diff --check
git diff
python3 scripts/validate_ais_setup_v0560t.py
python3 scripts/validate_uninstall_v0560q_r4.py
bash -n install.sh scripts/install/update_existing.sh uninstall.sh
```

Marcel's existing-install test: run `./install.sh --ais-setup`, complete the
browser wizard, and return to the terminal. On a clean install, follow the
same wizard stage inside `./install.sh`. Before starting a receiver manually,
inspect the result:

```bash
sudo python3 scripts/install/setup_ais.py --check
systemctl is-enabled sdrcc.service ais-catcher.service ais-catcher-control.service readsb.service sdrcc-traffic-voice.service
systemctl is-active sdrcc.service ais-catcher.service ais-catcher-control.service readsb.service sdrcc-traffic-voice.service
curl -s -o /dev/null -w 'Dashboard HTTP %{http_code}\n' http://127.0.0.1:8080/api/status
```

Expected boot state: `enabled` for sdrcc; `disabled` for the receiver services.
Expected runtime state without a FlexGround receiver request: `active` for
sdrcc; `inactive` for the receiver services. Then start AIS from FlexGround,
check actual reception, stop it again and verify that the receiver is released.
Finally reboot: the dashboard must return, and receivers must follow
FlexGround's configured runtime requests rather than their own boot autostart.

Also test a clean installation with **d**/deferred setup, followed by
`--ais-setup`, and Ctrl-C during setup. After an interruption, the receiver
services must be stopped and disabled; rerun the resume command to finish.
If service cleanup fails, the command fails and does not restart FlexGround
into a possible receiver conflict. Inspect the named service before retrying.

## Upstream references

- [Managed mode and the `-E` command](https://jvde-github.github.io/AIS-catcher-docs/managed/dashboard/)
- [Official setup wizard](https://jvde-github.github.io/AIS-catcher-docs/managed/setup-wizard/)
- [Wizard configuration save implementation](https://github.com/jvde-github/AIS-catcher/blob/main/frontend/control/js/wizard.js)

No station serials, locations or credentials are embedded by this patch.
