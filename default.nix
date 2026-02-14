# Nix package for the Ricky webhook handler.
# Wraps the Python app with all dependencies and creates a `ricky-server` binary.
#
# Usage: nix-build default.nix
# Run:   result/bin/ricky-server --host 0.0.0.0 --port 8000
{
  pkgs ? import <nixpkgs> { },
}:

let
  pythonEnv = pkgs.python3.withPackages (
    ps: with ps; [
      fastapi
      uvicorn
      pyjwt
      cryptography
      httpx
      google-auth
      requests
      pydantic
      pydantic-settings
    ]
  );
in
pkgs.stdenv.mkDerivation {
  pname = "ricky";
  version = "0.1.0";
  src = ./.;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib/ricky $out/bin
    cp -r src $out/lib/ricky/
    makeWrapper ${pythonEnv}/bin/uvicorn $out/bin/ricky-server \
      --set PYTHONPATH "$out/lib/ricky" \
      --add-flags "src.main:app"
    runHook postInstall
  '';

  meta.description = "Ricky LaFleur GitHub App — TPB-themed code reviewer";
}
