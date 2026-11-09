{ pkgs }:
let
  soloist = import ./soloist.nix { inherit pkgs; inherit (pkgs) lib; };
  spotify-player = pkgs.spotify-player.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ ./spotify-player-oauth.patch ];
  });
in pkgs.python3Packages.buildPythonApplication {
  pname = "spotify-island";
  version = "1.1.0";
  src = ../.;
  pyproject = true;
  build-system = [ pkgs.python3Packages.setuptools ];
  dependencies = with pkgs.python3Packages; [ dbus-next websockets tomli-w ];
  makeWrapperArgs = [
    "--prefix" "PATH" ":" "${pkgs.lib.makeBinPath [ soloist spotify-player pkgs.systemd pkgs.libnotify pkgs.noctalia ]}"
  ];
  pythonImportsCheck = [ "spotify_island.cli" "spotify_island.control" "spotify_island.mpris" ];
  nativeCheckInputs = [ pkgs.python3Packages.pytestCheckHook ];
  pytestFlags = [ "tests" ];
  meta = {
    description = "Standalone Spotify Island runtime and Noctalia plugin";
    license = pkgs.lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "spotify-island";
  };
}
