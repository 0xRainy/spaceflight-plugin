# spaceflight-omarchy-hook
# Official omarchy plugin add/remove never runs plugin hooks.

omarchy() {
  command omarchy "$@"
  local rc=$?
  local plug="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/0xrainy.spaceflight"
  local setup="$plug/scripts/plugin-setup"
  local td="${XDG_CONFIG_HOME:-$HOME/.config}/spaceflight/teardown"
  if (( rc == 0 )); then
    if [[ ${1:-} == plugin && ( ${2:-} == add || ${2:-} == install ) ]]; then
      [[ -x $setup && -t 0 && -t 1 ]] && "$setup" || true
    elif [[ ${1:-} == plugin && ${2:-} == enable && ${3:-} == 0xrainy.spaceflight ]]; then
      [[ -x $setup && -t 0 && -t 1 ]] && "$setup" || true
    elif [[ ${1:-} == plugin && ( ${2:-} == remove || ${2:-} == rm ) ]]; then
      if [[ ! -e $plug && -x $td ]]; then
        "$td" || true
      fi
    fi
  fi
  return "$rc"
}
