#!/usr/bin/env bash
# Publish frontend/dist as <commit>/ on the web-builds branch, which install.sh unpacks
# instead of building the interface on the server. Keeps the newest $KEEP builds; the
# branch is a single commit, replaced each time, so its history doesn't grow.
set -euo pipefail

BRANCH="web-builds"
KEEP=30
sha="${GITHUB_SHA:?}"
repo="$(git rev-parse --absolute-git-dir)"
work="$(mktemp -d)"

if git fetch --quiet --depth=1 origin "$BRANCH"; then
  git archive FETCH_HEAD | tar -x -C "$work"
fi
rm -rf "${work:?}/$sha"
cp -r frontend/dist "$work/$sha"

{ echo "$sha"; grep -vx "$sha" "$work/builds.txt" 2>/dev/null || true; } | head -n "$KEEP" >"$work/builds.new"
mv "$work/builds.new" "$work/builds.txt"
for dir in "$work"/*/; do
  grep -qx "$(basename "$dir")" "$work/builds.txt" || rm -rf "$dir"
done
cat >"$work/README.md" <<'EOF'
Built web interfaces for recent commits on main, published by CI after the tests pass.
install.sh unpacks the directory named after the commit it installs. Don't edit by hand.
EOF

export GIT_INDEX_FILE="$work.index"
git --git-dir="$repo" --work-tree="$work" -C "$work" add -A
tree="$(git --git-dir="$repo" write-tree)"
commit="$(git --git-dir="$repo" commit-tree "$tree" -m "Web interface builds (newest: $sha)")"
git push --quiet --force origin "$commit:refs/heads/$BRANCH"
echo "published $sha; $(wc -l <"$work/builds.txt") builds kept"
