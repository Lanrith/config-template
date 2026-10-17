# Lanrith configuration template

Use this template to create a **private** repository for your router's hardware
and network intent. GitHub can propose platform updates, validate reviewed
changes, assemble an owner-signed image and publish a private deployment release.
Your network configuration and deployment provenance stay in your repository.

Platform selection requires a published release with passing native and
supply-chain evidence. Missing, stale or revoked evidence blocks assembly.
A template and a signed prerelease do not establish production readiness.

## Setup

Local commands require Python 3 with PyYAML, GitHub CLI and OpenSSL.

1. Create a private repository from this template with `main` as its default
   branch. Replace the synthetic selectors, addresses and administrator key in
   `config.yaml`. Enable only the services you need.
   Run `python3 scripts/initialize.py` once to generate the permanent device
   identity. Commit this field and preserve it across updates, key rotation and
   recovery; changing it breaks encrypted state discovery. For an existing
   installation, retain its current machine ID instead of generating a new one.
2. Use your established key-management process to create or select a boot/verity
   key and certificate, and a **separate** deployment-evidence key/certificate.
   Keep the private keys outside Git. Commit only the public certificates at
   `trust/boot.crt` and `trust/evidence.crt`.
3. Run `python3 scripts/update-platform.py` to select a qualified platform and pin
   its artifacts and reusable workflow. Review and commit the resulting lock
   and workflow diff. Push this reviewed bootstrap commit to `main` before
   selecting a signing profile below. Setup fails clearly if no qualified
   release exists.
   This template also refuses an older qualified workflow that lacks its
   signing-profile interface, before changing the existing lock.
4. Select a signing profile as a repository administrator. The default
   `protected` profile uses `python3 scripts/setup.py OWNER/REPO
   --configure-protections`. It installs a main-branch ruleset requiring review
   and configuration checks, and three environments restricted to protected
   branches. For a private repository on GitHub Free, use `python3
   scripts/setup.py OWNER/REPO --signing-profile repository`. This uses ordinary
   repository Actions secrets and trusts every repository writer. Both commands
   set the non-secret repository variable `LANRITH_SIGNING_PROFILE`; the default
   remains `protected` if it is unset. See [signing profiles](#signing-profiles).
5. Import the existing private material using `scripts/setup.py OWNER/REPO
   --import-keys --boot-key /private/boot.key --evidence-key /private/evidence.key`.
   Add `--signing-profile repository` for the repository-secret profile. The
   command checks key/certificate matches and separate authorities, reads from
   protected local files, and writes secrets through standard input into the
   selected scope. It does not generate keys. Store recovery copies offline.
6. Configure the update authority in `lanrith-updates` for the protected profile,
   or as repository secrets for the repository profile. Prefer a GitHub App
   installed only on this configuration repository, with Contents, Pull requests
   and Workflows read/write permissions. Give it no branch-protection bypass.
   Import its existing private key with `scripts/setup.py OWNER/REPO
   --import-update-credentials --update-app-id APP_ID --update-app-key
   /private/update-app.key`. A repository-scoped fine-grained token with the same
   permissions is an alternative: use `--update-token /private/update.token`.
   Add `--signing-profile repository` when importing repository credentials.
   Select one authority and retain its normal rotation process. The default
   `GITHUB_TOKEN` cannot update the pinned workflow files.
7. Push reviewed configuration through a pull request. Merging to main builds
   and publishes a private deployment release. Deployment and reboot are
   separate operator actions.

The protected profile requires an independent approving reviewer. A sole
maintainer can review update pull requests authored by the configured GitHub
App. For changes you author yourself, use a trusted reviewer or the local build
path; GitHub does not permit self-approval under this policy. Repository-secret
users must manage their own review process and restrict write access to
trusted people.

## Signing profiles

| Profile | Key storage | Repository writer access | GitHub plan |
| --- | --- | --- | --- |
| `protected` (default) | Separate signing, evidence and update environments | Main reviews and checks are enforced; signing environments allow protected branches only | A plan supporting private rulesets and environments |
| `repository` | Repository Actions secrets; separate boot and evidence keys | Every writer is trusted with signing authority because a writer can change workflows to request secrets | Works with private repositories on Free |

GitHub documents [repository secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
and [private environment availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
There is no automatic fallback between profiles. Setup refuses an existing
profile mismatch before importing keys. To change profiles, review who can
write workflows, remove the old secrets and variable, then rerun setup for the
new scope.

Both profiles admit the public platform before accessing keys, allow signing
only on a main-branch push or manual run, assemble offline and sign evidence
on a separate runner. The build workflow requires its own successful
configuration check before calling the signing workflow, including on accounts
without branch protection. Pull requests have no signing path. Repository scope
cannot stop a repository writer from creating a different workflow that reads
the same secrets; use the protected or
[local build path](https://github.com/Lanrith/lanrith/blob/main/docs/build-and-trust.md)
when that trust model does not fit.

Boot secrets are `LANRITH_BOOT_KEY` and `LANRITH_BOOT_CERTIFICATE` in
`lanrith-signing`. Evidence secrets are `LANRITH_EVIDENCE_KEY` and
`LANRITH_EVIDENCE_CERTIFICATE` in `lanrith-evidence`. In repository mode, those
four names are repository secrets instead. A certificate is public; its
corresponding private key is the credential. Optional serial login also needs
`LANRITH_SERIAL_PASSPHRASE_HASH` in the selected boot scope; supply the scrypt
hash using your private provisioning process, never in Git or a command argument.

Update authority is separate: `LANRITH_UPDATE_APP_ID` is an Actions variable
and `LANRITH_UPDATE_APP_PRIVATE_KEY` is a secret, or use the
`LANRITH_UPDATE_TOKEN` secret. Use the selected profile's repository or
`lanrith-updates` scope. The update job receives only its update credential and
requests only the three repository permissions above. Repository writers can
change that job too; environment isolation is provided by the protected profile.

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
The scoped App/token makes the proposal's normal PR checks run automatically.
See the [PR action's token requirements](https://github.com/peter-evans/create-pull-request#token)
when configuring or rotating this authority.

PR validation uses the compiler selected by the reviewed base branch. A
proposed platform compiler and build workflow run only after that update is
reviewed and merged to main. If an update adds configuration fields, merge its
platform selection first, then propose the new fields against that compiler.

The reusable workflow verifies the platform, compiler and matching builder
before extracting or executing them. It assembles offline with boot keys in
private tmpfs, then signs private DSSE SLSA evidence on a fresh job with a
separate authority. Private provenance records the signing profile and whether
environment protection was required. It does not certify an owner image's
SLSA level; the public platform's assessed SLSA Build L3 evidence remains
independently verified in both profiles. No public transparency log is used
for owner provenance. Review that privacy boundary before enabling public
keyless owner provenance or making this repository public.

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
