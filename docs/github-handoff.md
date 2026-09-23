# GitHub handoff

The source repository is public and was inspected, but the configured GitHub CLI credential for `kerk1v` is invalid. GitHub therefore cannot be used from this environment to create the `MyOTA` organization or push repositories.

Organization creation is an account-level GitHub action and may require the account owner to complete an interactive web step. Once the organization exists and `gh auth login -h github.com` succeeds, run `scripts/publish-github.sh`, split the bootstrap paths using [`repository-map.md`](repository-map.md), and push the resulting repositories.

The existing `ea7klk/mpota` repository has not been modified.

