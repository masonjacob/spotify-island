{
  description = "Spotify Island for Noctalia with Soloist playback and Spotify library controls";
  outputs = { self }: {
    homeManagerModules.default = import ./nix/home-manager.nix;
    homeManagerModules.spotify-island = self.homeManagerModules.default;
  };
}
