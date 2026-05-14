# Changelog

All notable changes to hathor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.4] - 2026-05-14

### Changed

- Bumped requests to v2.34.1

## [2.1.3] - 2026-05-12

### Changed

- Bumped requests to v2.34.0

## [2.1.2] - 2026-05-10

### Added
- GitLab Release is now published automatically on each new tag, with release notes pulled from the matching CHANGELOG section
- Renovate MRs now bump CHANGELOG.md alongside VERSION via the shared bump-version template's BUMP_CHANGELOG option

### Changed
- Source tarballs attached to GitLab Releases now contain only the runnable package plus install metadata (`LICENSE.rst`, `pyproject.toml`, `VERSION`); tests, CI configs, Dockerfile, and top-level docs are excluded via `.gitattributes`
