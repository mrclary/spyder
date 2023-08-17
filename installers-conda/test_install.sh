#!/bin/bash

PKG_PATH=$1

# ---- Install Spyder
if [[ "$OSTYPE" = "darwin"* ]]; then
    # Stream install.log to stdout to view all log messages.
    tail -F /var/log/install.log & tail_id=$!
    trap "kill -s TERM $tail_id" EXIT

    installer -pkg $PKG_PATH -target CurrentUserHomeDirectory >/dev/null
elif [[ "$OSTYPE" = "msys" ]]; then
    # There is no way to view log messages from NSIS installer.
    $PKG_PATH /InstallationType=JustMe /NoRegistry=1 /S
else
    $PKG_PATH -b
fi

# ---- Show Install Results
echo "Install info:"
if [[ "$OSTYPE" = "darwin"* ]]; then
    root_prefix=$(compgen -G $HOME/Library/spyder-*)
    shortcut_path=$HOME/Applications/Spyder.app

    echo "Contents of ${root_prefix}:"
    ls -al $root_prefix
    echo -e "\nContents of ${root_prefix}/uninstall-spyder.sh:"
    cat $root_prefix/uninstall-spyder.sh
    echo -e "\nContents of $HOME/.bashrc:"
    cat $HOME/.bashrc

    if [[ -e "$shortcut_path" ]]; then
        echo "Contents of $shortcut_path/Contents/MacOS:"
        ls -al $shortcut_path/Contents/MacOS
        echo -e "\nContents of $shortcut_path/Contents/Info.plist:"
        cat $shortcut_path/Contents/Info.plist
        echo -e "\nContents of $shortcut_path/Contents/MacOS/spyder-script:"
        cat $shortcut_path/Contents/MacOS/spyder-script
    else
        echo "$shortcut_path does not exist"
        exit 1
    fi
elif [[ "$OSTYPE" = "msys" ]]; then
    root_prefix=$(compgen -G $LOCALAPPDATA/spyder-*)
    shortcut_path="$APPDATA/Roaming/Microsoft/Windows/Start Menu/spyder/Spyder.lnk"

    echo "Contents of ${root_prefix}:"
    ls -al $root_prefix

    if [[ -e "$shortcut_path" ]]; then
        echo -e "\nContents of ${shortcut_path}:"
        cat $shortcut_path
    else
        echo "$shortcut_path does not exist"
        exit 1
    fi
else
    root_prefix=$(compgen -G $HOME/.local/spyder-*)
    shortcut_path=$HOME/.local/share/applications/spyder_spyder.desktop

    echo "Contents of ${root_prefix}:"
    ls -al $root_prefix
    echo -e "\nContents of ${root_prefix}/uninstall-spyder.sh:"
    cat $root_prefix/uninstall-spyder.sh
    echo -e "\nContents of $HOME/.bashrc:"
    cat $HOME/.bashrc

    if [[ -e "$shortcut_path" ]]; then
        echo -e "\nContents of ${shortcut_path}:"
        cat $shortcut_path
    else
        echo "$shortcut_path does not exist"
        exit 1
    fi
fi

# ---- Verify Spyder Launched
if [[ "$OSTYPE" = "msys" ]]; then
    spy_running_cmd="tasklist.exe | grep python.exe >/dev/null"
else
    spy_running_cmd="pgrep -f spyder-runtime/bin/spyder 2>/dev/null"
fi
t=20
while [[ $t > 0 && ! $($spy_running_cmd) ]]; do
    log "Wating for Spyder to launch..."
    sleep 1
    ((t -= 1))
done
if [[ $t > 0 ]]; then
    log "Spyder launched successfully after install in $((20 - t))s"
else
    log "Spyder failed to launch"
    exit 1
fi
