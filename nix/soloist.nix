{ pkgs, lib }:
pkgs.stdenv.mkDerivation {
  pname = "spotify-soloist";
  version = "1.3.10";
  src = pkgs.fetchurl {
    url = "https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz";
    hash = "sha256-wyNJujuvg2pEqFwg7dIwAKJWUzCf3fIbUII7chz8fGo=";
  };
  sourceRoot = ".";
  nativeBuildInputs = [ pkgs.autoPatchelfHook ];
  buildInputs = [ pkgs.stdenv.cc.cc.lib ];
  runtimeDependencies = [ pkgs.pipewire pkgs.libpulseaudio pkgs.alsa-lib ];
  installPhase = ''
    runHook preInstall
    install -Dm755 soloist $out/bin/soloist
    install -Dm644 THIRD_PARTY_LICENSES.txt $out/share/doc/spotify-soloist/THIRD_PARTY_LICENSES.txt
    runHook postInstall
  '';
  preferLocalBuild = true;
  allowSubstitutes = false;
  meta = {
    description = "Official headless Spotify Connect player";
    homepage = "https://developer.spotify.com/documentation/soloist";
    license = lib.licenses.unfree;
    platforms = [ "x86_64-linux" ];
    mainProgram = "soloist";
  };
}
