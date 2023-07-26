#!/bin/bash

launch_timeout=10
error_timeout=30
quit_timeout=10
interval=1

help() { cat <<EOF

$(basename $0) [options] cmd [cmd args]
Launch Spyder with cmd and arguments.
Timeouts are used for launching, running, and quitting.

  -l launch_timeout
              Number of seconds to wait for Spyder to launch.
              Default value: $launch_timeout seconds.

  -e error_timeout
              Number of seconds to wait for Spyder to produce errors while
              running.
  -q quit_timeout
              Number of seconds to wait for Spyder to quit.

  -i interval Polling interval for timeouts.
              Positive integer, default value: $interval seconds.

  cmd         Command for launching Spyder.

EOF
}

log(){
    echo "$(date "+%Y-%m-%d %H:%M:%S") [test_app] -> $@"
}

# Options.
while getopts ":t:i:d:" option; do
    case "$option" in
        l) launch_timeout=$OPTARG ;;
        e) error_timeout=$OPTARG ;;
        q) quit_timeout=$OPTARG ;;
        i) interval=$OPTARG ;;
        *) help; exit 0 ;;
    esac
done
shift $(($OPTIND - 1))

if [[ "$OSTYPE" = "msys" ]]; then
    root_prefix=$(compgen -G $LOCALAPPDATA/spyder-*)
    spy_launch_cmd="$root_prefix/envs/spyder-runtime/Scripts/spyder"
    spy_running_cmd="tasklist.exe | grep python.exe >/dev/null"
    spy_quit_cmd="taskkill.exe /T /fi python*"
elif [[ "$OSTYPE" = "darwin"* ]]; then
    spy_launch_cmd="$HOME/Applications/Spyder.app/Contents/MacOS/spyder"
    spy_running_cmd="pgrep -f spyder-runtime/bin/spyder 2>/dev/null"
    spy_quit_cmd="pkill -SIGTERM -f spyder-runtime/bin/spyder"
else
    root_prefix=$(compgen -G $HOME/.local/spyder-*)
    spy_launch_cmd="$root_prefix/envs/spyder-runtime/bin/spyder"
    spy_running_cmd="pgrep -f spyder-runtime/bin/spyder 2>/dev/null"
    spy_quit_cmd="pkill -SIGTERM -f spyder-runtime/bin/spyder"
fi

log "Launching Spyder..."
INSTALLER_TEST=1 ${spy_launch_cmd} &

t=$launch_timeout
sleep $interval
while [[ $t > 0 && ! $($spy_running_cmd) ]]; do
    log "Wating for Spyder to launch..."
    sleep $interval
    ((t -= interval))
done
if [[ $t > 0 ]]; then
    log "Spyder launched successfully"
else
    log "Spyder failed to launch in ${launch_timeout}s"
    exit 1
fi

log "Waiting for possible errors..."
t=$error_timeout
while [[ $t > 0 && $($spy_running_cmd) ]]; do
    sleep $interval
    ((t -= interval))
done
if [[ $t > 0 ]]; then
    log "Spyder unexpectedly quit after $((error_timeout - t))s"
    exit 1
else
    log "Spyder did not raise any errors in ${error_timeout}s"
fi

log "Quitting Spyder..."
$spy_quit_cmd

t=$quit_timeout
sleep $interval
while [[ $t > 0 && $($spy_running_cmd) ]]; do
    sleep $interval
    ((t -= $interval))
done
if [[ $t > 0 ]]; then
    log "Spyder shut down successfully in $((quit_timeout - t))s"
else
    log "Spyder did not shut down properly in ${quit_timeout}s"
    exit 1
fi
