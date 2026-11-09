{ config, lib, pkgs, ... }:
let
  soloist = import ../runtime/spotify-soloist.nix { inherit pkgs lib; };
  soloistPython = pkgs.python3.withPackages (ps: [ ps.dbus-next ps.websockets ]);
  soloistStart = pkgs.writeShellScript "spotify-soloist-start" ''
    key_file="${config.xdg.configHome}/spotify-soloist/api-key"
    if [ ! -s "$key_file" ]; then
      echo "Save your Soloist API key in $key_file (mode 600)." >&2
      exit 1
    fi
    device_name=$(${pkgs.nettools}/bin/hostname | ${pkgs.gnused}/bin/sed 's/^./\U&/')
    exec ${lib.getExe soloist} --device-name "Noctalia $device_name" \
      --api-key "$(< "$key_file")" --ws 127.0.0.1:0 --cache-size 512
  '';
in {
  options.programs.spotify-island.enable = lib.mkEnableOption "Spotify Island for Noctalia";
  config = lib.mkIf config.programs.spotify-island.enable {
    programs.noctalia = {
      enable = true;
      settings = {
        plugins.enabled = [ "mason/spotify-island" ];
        plugins.source = [{ name = "spotify-island"; kind = "path"; location = toString ../plugins; enabled = true; }];
        widget.spotify = {
          type = "mason/spotify-island:now-playing";
          actions.left = "panel-toggle mason/spotify-island:island";
        };
      };
    };
    # spotify_player serves account/library requests only. Soloist owns playback.
    programs.spotify-player = {
      enable = true;
      # Keep ncspot's library/fallback callback separate from the official
      # Spotify streaming callback. A global URI override breaks streaming.
      package = pkgs.spotify-player.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ../runtime/spotify-player-oauth.patch ];
      });
      settings = {
        # Official librespot streaming registration uses port 5588.
        login_redirect_uri = "http://127.0.0.1:5588/login";
        enable_streaming = "Never";
        enable_media_control = false;
        enable_notify = false;
      };
    };
    systemd.user.services.spotify-background = {
      Unit = {
        Description = "Spotify Soloist background playback";
        After = [ "graphical-session.target" "pipewire.service" ];
        PartOf = [ "graphical-session.target" ];
        ConditionPathExists = "${config.xdg.configHome}/spotify-soloist/api-key";
      };
      Service = {
        ExecStart = "${soloistStart}";
        Restart = "on-failure";
        RestartSec = 10;
        RestartPreventExitStatus = [ 10 ];
        UMask = "0077";
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };
    systemd.user.services.spotify-soloist-mpris = {
      Unit = {
        Description = "Local Spotify Soloist media controls for Noctalia";
        After = [ "spotify-background.service" ];
        PartOf = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${soloistPython}/bin/python3 ${../runtime/spotify-soloist-mpris.py}";
        Environment = "PATH=${lib.makeBinPath [ pkgs.libnotify ]}";
        Restart = "on-failure";
        RestartSec = 3;
        UMask = "0077";
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };

    home.packages = [
      soloist
      pkgs.spotify
      (pkgs.writeShellApplication {
        name = "spotify-quick-control";
        runtimeInputs = [ pkgs.python3 pkgs.noctalia pkgs.libnotify pkgs.systemd soloist config.programs.spotify-player.package ];
        text = ''exec python3 ${../runtime/spotify-quick-control.py} "$@"'';
      })
      (pkgs.writeShellApplication {
        name = "spotify-background-setup";
        runtimeInputs = [ soloist pkgs.systemd pkgs.coreutils ];
        text = ''
          key_file=${lib.escapeShellArg "${config.xdg.configHome}/spotify-soloist/api-key"}
          if [ ! -s "$key_file" ]; then
            install -d -m 700 "$(dirname "$key_file")"
            read -r -s -p "Spotify Soloist API key: " soloist_key
            echo
            if [ -z "$soloist_key" ]; then echo "No key supplied." >&2; exit 1; fi
            (umask 077; printf '%s\n' "$soloist_key" > "$key_file")
            unset soloist_key
          fi
          chmod 600 "$key_file"
          systemctl --user restart spotify-background.service spotify-soloist-mpris.service
          echo "Select Noctalia on this machine from Spotify's Connect devices to pair it."
          sleep 2
          soloist ctl status
        '';
      })

    ];
  };
}
