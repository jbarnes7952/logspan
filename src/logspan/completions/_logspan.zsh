#compdef logspan

# zsh completion for logspan
# Install: copy to a directory in $fpath (e.g. ~/.zsh/completions) and run
#   compinit; or put  eval "$(logspan --completion zsh)" in .zshrc.

_logspan() {
  local -a globs
  globs=(
    '*.log:log files' '*.txt:text files' '*.json:JSON logs'
    '*.txt,*.log:text and log files'
    'redpanda-*-redpanda.txt:Redpanda broker logs (debug bundle)'
    'redpanda-*-sidecar.txt:Redpanda sidecar logs (debug bundle)'
  )
  _arguments -s -S \
    '(-j --json)'{-j,--json}'[JSON output, one object per file]' \
    '(-r --recursive)'{-r,--recursive}'[descend into subdirectories]' \
    '*'{-g,--glob}'[only consider files whose name matches PAT]:pattern:->glob' \
    '--skip-empty[omit zero-byte files]' \
    '--full-path[show the full path instead of the path relative to the dir argument]' \
    '--completion[print shell completion script]:shell:(zsh)' \
    '(- *)'{-h,--help}'[show help]' \
    '(- *)'{-V,--version}'[show version]' \
    '*:file or directory:_files'
  case $state in
    glob) _describe -t patterns 'glob pattern' globs ;;
  esac
}

_logspan "$@"
