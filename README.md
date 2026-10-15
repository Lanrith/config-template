# Lanrith configuration template

Use this template to create a **private** repository for your router's hardware
and network intent. GitHub can then propose platform updates, validate reviewed
changes, assemble an owner-signed image and publish a private deployment release.
Your network configuration and deployment provenance stay in your repository.

The OS is currently in qualification. Setup intentionally refuses a platform
without the required native and supply-chain evidence. A template and a signed
prerelease do not establish production readiness.

## Setup

1. Create a private repository from this template with `main` as its default
   branch. Replace the synthetic selectors, addresses and administrator key in
   `config.yaml`. Enable only the services you need.
2. Use your established key-management process to create or select a boot/verity
   key and certificate, and a **separate** deployment-evidence key/certificate.
   Keep the private keys outside Git. Commit only the public certificates at
   `trust/boot.crt` and `trust/evidence.crt`.
3. Run `python3 scripts/update-platform.py` to select a qualified platform and pin
   its artifacts and reusable workflow. Review and commit the resulting lock
   and workflow diff. Setup fails clearly if no qualified release exists.
4. As a repository administrator, run `python3 scripts/setup.py OWNER/REPO
   --configure-protections`. This installs a main-branch ruleset requiring review
   and configuration checks, and two environments restricted to protected
   branches. It checks the account's actual capabilities. Private repository
   environment features depend on the GitHub plan; unsupported accounts use the
   [local build path](https://github.com/Lanrith/lanrith/blob/main/docs/build-and-trust.md).
5. Import the existing private material using `scripts/setup.py OWNER/REPO
   --import-keys --boot-key /private/boot.key --evidence-key /private/evidence.key`.
   The command checks key/certificate matches, reads from protected local files,
   and writes GitHub environment secrets through standard input. It does not
   generate keys. Store recovery copies offline.
6. Push reviewed configuration through a pull request. Merging to protected main
   builds and publishes a private deployment release. Deployment and reboot are
   separate operator actions.

Boot secrets are `LANRITH_BOOT_KEY` and `LANRITH_BOOT_CERTIFICATE` in
`lanrith-signing`. Evidence secrets are `LANRITH_EVIDENCE_KEY` and
`LANRITH_EVIDENCE_CERTIFICATE` in `lanrith-evidence`. Optional serial login also
needs `LANRITH_SERIAL_PASSPHRASE_HASH` in the boot environment; supply the scrypt
hash using your private provisioning process, never in Git or a command argument.

An owner deployment sequence is `release.sequence_floor + GITHUB_RUN_NUMBER`.
If you recreate the workflow/repository or restore an older checkout, raise the
floor above every previously issued deployment sequence before building. Never
reuse a sequence. Check the signed deployment metadata before staging.

## Updates and trust

The daily 04:17 UTC job proposes a new qualified platform lock and matching
reusable workflow commit. It verifies published provenance but does not merge
or approve its own PR. Review source/workflow pins and security changes. Merged
changes trigger the full private build. A fresh inventory-bound security
assessment is required even if the platform version has not changed.

The reusable workflow verifies the platform, compiler and matching builder
before extracting or executing them. It assembles offline with boot keys in
private tmpfs, then signs private DSSE SLSA evidence on a fresh job with a
separate authority. It does not publish your repository identity to a public
transparency log. Require deliberate review before enabling public keyless
owner provenance or making this repository public.

## Integrations

Built-in DNS, DHCP and NTP need only configuration flags. Advanced integrations
have exact reviewed file inventories, feature declarations, health units and
manifest digests in `extensions.lock`. Place their files under
`extensions/ID/root/`; see the [OS integration contract](https://github.com/Lanrith/lanrith/blob/main/docs/configuration.md).
No owner build hooks run with keys present. Additional packages need separate
reviewed source, package and security evidence; flags do not install packages.

Keep private configuration, certificates, extensions, published images and
provenance backed up alongside an offline recovery key. See
[operations](https://github.com/Lanrith/lanrith/blob/main/docs/operations.md) before
an initial install, update, rollback or trust rotation.
