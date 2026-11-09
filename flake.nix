{
  description = "Standalone Spotify Island runtime and Noctalia plugin";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/1d060086d60cb76a40cf37109f979d88a5bd6396";
  outputs = { self, nixpkgs }: let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
    package = import ./nix/package.nix { inherit pkgs; };
  in {
    packages.${system}.default = package;
    apps.${system}.default = { type = "app"; program = "${package}/bin/spotify-island"; };
    checks.${system}.default = package;
  };
}
