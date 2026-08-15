# spaceflight-omarchy-hook
# Official `omarchy plugin add` never runs plugin install hooks. After it
# finishes enable + bar placement, continue Spaceflight setup in this TTY.

omarchy() {
  command omarchy "$@"
  local rc=$?
  local setup="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/0xrainy.spaceflight/scripts/plugin-setup"
  if (( rc == 0 )) && [[ -x $setup && -t 0 && -t 1 ]]; then
    if [[ ${1:-} == plugin && ( ${2:-} == add || ${2:-} == install ) ]]; then
      "$setup" || true
    elif [[ ${1:-} == plugin && ${2:-} == enable && ${3:-} == 0xrainy.spaceflight ]]; then
      "$setup" || true
    fi
  fi
  return "$rc"
}
