#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RECEIPT="/var/lib/sdrcc/install-receipt"
SYSTEM_ROOT=""
if [[ "${SDRCC_INSTALL_TEST_MODE:-0}" == 1 ]]; then
  RECEIPT="${SDRCC_INSTALL_RECEIPT:-$RECEIPT}"
  SYSTEM_ROOT="${SDRCC_SYSTEM_ROOT:-}"
fi
ASSUME_YES=0
PURGE_EXTERNAL=0

usage(){
  cat <<'EOF'
Usage: ./uninstall.sh [--yes] [--purge-external]

Removes FlexGround SDR completely: source, virtual environment, configuration,
runtime data, logs, services, sudoers rules and privileged helper.

By default, external radio applications are removed only when the installation
receipt proves that install.sh added them. Use --purge-external for an older
installation without a receipt, or to remove the complete radio stack even when
some components existed before FlexGround SDR.
EOF
}

while (($#)); do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --purge-external) PURGE_EXTERNAL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

sys(){ printf '%s%s' "$SYSTEM_ROOT" "$1"; }
receipt_value(){
  [[ -n "$RECEIPT" && -r "$RECEIPT" ]] || return 0
  awk -F= -v key="$1" '$1 == key { value=substr($0, index($0, "=")+1) } END { print value }' "$RECEIPT"
}
receipt_is(){ [[ "$(receipt_value "$1")" == "$2" ]]; }
remove_component(){ ((PURGE_EXTERNAL)) || receipt_is "$1" 1; }

validate_project_root(){
  [[ "$ROOT" == /* && "$ROOT" != / ]] || { echo "FAIL: unsafe project path: $ROOT"; exit 3; }
  [[ "$ROOT" != "$(getent passwd "${SUDO_USER:-${USER:-nobody}}" 2>/dev/null | cut -d: -f6)" ]] || {
    echo "FAIL: refusing to remove a home directory: $ROOT"; exit 3;
  }
  [[ -f "$ROOT/VERSION" && -f "$ROOT/install.sh" && -d "$ROOT/core" && -d "$ROOT/dashboard" ]] || {
    echo "FAIL: $ROOT is not recognisable as a FlexGround SDR installation"; exit 3;
  }
}

validate_receipt(){
  [[ -e "$RECEIPT" ]] || return 0
  if [[ -z "$SYSTEM_ROOT" && "$(stat -c %u "$RECEIPT" 2>/dev/null || echo -1)" != 0 ]]; then
    echo "WARN: ignoring installation receipt because it is not owned by root: $RECEIPT"
    RECEIPT=""
    return 0
  fi
  local encoded recorded_root
  encoded="$(receipt_value project_root_b64)"
  if [[ -n "$encoded" ]]; then
    recorded_root="$(printf '%s' "$encoded" | base64 -d 2>/dev/null || true)"
    [[ "$recorded_root" == "$ROOT" ]] || {
      echo "FAIL: this uninstaller belongs to $ROOT, but the receipt belongs to $recorded_root"
      exit 3
    }
  fi
}

restore_service_state(){
  local key="$1" service="$2" enabled active
  enabled="$(receipt_value "${key}_enabled")"
  active="$(receipt_value "${key}_active")"
  [[ "$enabled" == 1 ]] && sudo systemctl enable "$service" >/dev/null 2>&1 || true
  [[ "$enabled" == 0 ]] && sudo systemctl disable "$service" >/dev/null 2>&1 || true
  [[ "$active" == 1 ]] && sudo systemctl start "$service" >/dev/null 2>&1 || true
  [[ "$active" == 0 ]] && sudo systemctl stop "$service" >/dev/null 2>&1 || true
}

purge_package_owning(){
  local path="$1" package
  package="$(dpkg-query -S "$path" 2>/dev/null | head -1 | cut -d: -f1 || true)"
  [[ -z "$package" ]] || sudo apt-get purge -y "$package"
}

restore_or_remove_file(){
  local path="$1" was_preexisting="$2" backup="${1}.before-flexground-initialization"
  if [[ "$was_preexisting" == 1 && -f "$backup" ]]; then
    sudo mv -f "$backup" "$path"
  elif [[ "$was_preexisting" == 0 || "$PURGE_EXTERNAL" == 1 ]]; then
    sudo rm -f "$path" "$backup"
  fi
}

validate_project_root
validate_receipt

if [[ ! -r "$RECEIPT" && "$PURGE_EXTERNAL" == 0 ]]; then
  echo "WARN: no trusted installation receipt; external radio applications will be preserved."
  echo "      Use --purge-external only if you also want the complete radio stack removed."
fi

echo "This will permanently remove the complete FlexGround SDR installation at:"
echo "  $ROOT"
((PURGE_EXTERNAL)) && echo "It will also remove the complete external radio stack."
if ((ASSUME_YES == 0)); then
  read -r -p "Continue? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || exit 0
fi

sudo -v

echo "==> Stop FlexGround SDR services"
sudo systemctl disable --now sdrcc.service >/dev/null 2>&1 || true
sudo systemctl disable --now sdrcc-traffic-voice.service >/dev/null 2>&1 || true

echo "==> Remove FlexGround SDR system integration"
sudo rm -f \
  "$(sys /etc/systemd/system/sdrcc.service)" \
  "$(sys /etc/systemd/system/sdrcc-traffic-voice.service)" \
  "$(sys /etc/sudoers.d/sdrcc-readsb)" \
  "$(sys /etc/sudoers.d/sdrcc-receiver-roles)" \
  "$(sys /etc/sudoers.d/sdrcc-service-handover)" \
  "$(sys /etc/sudoers.d/sdrcc-services)" \
  "$(sys /etc/sudoers.d/sdrcc-traffic-voice)" \
  "$(sys /etc/sudoers.d/sdrcc-ais-autostart)" \
  "$(sys /etc/sudoers.d/sdrcc-self-autostart)" \
  "$(sys /usr/local/sbin/sdrcc-apply-receiver-roles)" \
  "$(sys /usr/local/sbin/sdrcc-disable-ais-autostart)" \
  "$(sys /usr/local/sbin/sdrcc-disable-self-autostart)"

remove_satdump=0; remove_readsb=0; remove_ais=0; remove_control=0; remove_airband=0
remove_component satdump_installed && remove_satdump=1 || true
remove_component readsb_installed && remove_readsb=1 || true
remove_component ais_catcher_installed && remove_ais=1 || true
remove_component ais_control_installed && remove_control=1 || true
remove_component airband_installed && remove_airband=1 || true

if ((remove_satdump || remove_readsb || remove_ais || remove_control || remove_airband)); then
  echo "==> Remove external radio applications installed by FlexGround SDR"
fi

if ((remove_satdump)); then
  sudo apt-get purge -y satdump satdump-data 2>/dev/null || true
  manifest=""
  [[ -z "$RECEIPT" ]] || manifest="$(dirname "$RECEIPT")/satdump-install-manifest.txt"
  if [[ -n "$manifest" && -f "$manifest" ]]; then
    while IFS= read -r installed_path; do
      case "$installed_path" in
        /usr/*) sudo rm -f -- "$(sys "$installed_path")" ;;
        *) echo "WARN: skipped unsafe SatDump manifest entry: $installed_path" ;;
      esac
    done < "$manifest"
  fi
  sudo rm -f -- "$(sys /usr/bin/satdump)" "$(sys /usr/local/bin/satdump)"
  sudo rm -rf -- "$(sys /usr/lib/satdump)" "$(sys /usr/share/satdump)"
fi

if ((remove_readsb)); then
  sudo systemctl disable --now readsb.service >/dev/null 2>&1 || true
  sudo apt-get purge -y readsb 2>/dev/null || true
  restore_or_remove_file "$(sys /etc/default/readsb)" "$(receipt_value readsb_config_preexisting)"
else
  restore_or_remove_file "$(sys /etc/default/readsb)" "$(receipt_value readsb_config_preexisting)"
  restore_service_state readsb_service readsb.service
fi

# Remove only our managed-mode override, including when the external AIS install is kept.
sudo rm -f -- "$(sys /etc/systemd/system/ais-catcher.service.d/90-flexground-managed.conf)"
sudo rmdir "$(sys /etc/systemd/system/ais-catcher.service.d)" 2>/dev/null || true
sudo systemctl daemon-reload

if ((remove_control)); then
  sudo systemctl disable --now ais-catcher-control.service >/dev/null 2>&1 || true
  sudo rm -f "$(sys /usr/bin/AIS-catcher-control)" "$(sys /etc/systemd/system/ais-catcher-control.service)"
else
  restore_service_state ais_control_service ais-catcher-control.service
fi

if ((remove_ais)); then
  sudo systemctl disable --now ais-catcher.service ais-catcher-reboot.service >/dev/null 2>&1 || true
  purge_package_owning /usr/bin/AIS-catcher
  sudo rm -f \
    "$(sys /usr/bin/AIS-catcher)" \
    "$(sys /etc/systemd/system/ais-catcher.service)" \
    "$(sys /etc/systemd/system/ais-catcher-reboot.service)" \
    "$(sys /var/log/aiscatcher-install.log)"
  sudo rm -rf -- "$(sys /usr/lib/ais-catcher)"
  if ((PURGE_EXTERNAL)) || ! receipt_is ais_config_preexisting 1; then
    sudo rm -rf -- "$(sys /etc/AIS-catcher)"
  else
    restore_or_remove_file "$(sys /etc/AIS-catcher/aiscatcher.json)" 1
  fi
  if ((PURGE_EXTERNAL)) || receipt_is ais_user_preexisting 0; then
    sudo userdel aiscatcher >/dev/null 2>&1 || true
    sudo groupdel aiscatcher >/dev/null 2>&1 || true
  fi
else
  restore_or_remove_file "$(sys /etc/AIS-catcher/aiscatcher.json)" "$(receipt_value ais_config_preexisting)"
  restore_service_state ais_service ais-catcher.service
fi

if ((remove_airband)); then
  sudo rm -rf -- "$(sys /opt/sdrcc/traffic_voice)"
  sudo rmdir "$(sys /opt/sdrcc)" >/dev/null 2>&1 || true
fi

install_user="$(receipt_value install_user)"
if [[ "$install_user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  receipt_is group_plugdev_preexisting 0 && sudo gpasswd -d "$install_user" plugdev >/dev/null 2>&1 || true
  receipt_is group_dialout_preexisting 0 && sudo gpasswd -d "$install_user" dialout >/dev/null 2>&1 || true
fi

sudo systemctl daemon-reload
sudo systemctl reset-failed >/dev/null 2>&1 || true
if [[ -n "$RECEIPT" ]]; then
  receipt_dir="$(dirname "$RECEIPT")"
  sudo rm -f -- "$RECEIPT" "$receipt_dir/satdump-install-manifest.txt"
  sudo rmdir "$receipt_dir" >/dev/null 2>&1 || true
fi

echo "==> Remove FlexGround SDR source, configuration, data and logs"
rm -rf -- "$ROOT"

echo "FlexGround SDR has been completely removed."
if ((PURGE_EXTERNAL == 0)); then
  echo "Pre-existing external radio applications and shared Ubuntu packages were preserved."
fi
