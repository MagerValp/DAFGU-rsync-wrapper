#!/bin/bash


PKGSCRIPTS=scripts
PKGVERSION="2.3"
PKGID="se.gu.gu.DAFGUMigration"
PKGFILE="DAFGUMigrationConf-$PKGVERSION.pkg"
PKGTARGET="10.5"
PKGTITLE="DAFGU Migration Configuration"

PACKAGEMAKER=""
if [ -e "/Developer/usr/bin/packagemaker" ]; then
    PACKAGEMAKER="/Developer/usr/bin/packagemaker"
else
    while read path; do
        if [ -e "$path/Contents/MacOS/PackageMaker" ]; then
            PACKAGEMAKER="$path/Contents/MacOS/PackageMaker"
            break
        fi
    done < <(mdfind "(kMDItemCFBundleIdentifier == com.apple.PackageMaker)")
fi
if [ -z "$PACKAGEMAKER" ]; then
    echo "packagemaker not found"
    exit 1
fi

echo "Packaging $PKGTITLE as $PKGID $PKGVERSION"

rm -f "$PKGFILE"
pkgroot=`mktemp -d -t dafgumigration`

echo "Creating directory structure"
mkdir -p "$pkgroot/private/var/root"
mkdir -p "$pkgroot/usr/local/munki"
cp -rp ssh "$pkgroot/private/var/root/.ssh"
chmod 0700 "$pkgroot/private/var/root/.ssh"
chmod 0600 "$pkgroot/private/var/root/.ssh/id_rsa"
cp run_backup.py dafgu_filter.txt "$pkgroot/usr/local/munki"
find "$pkgroot" -name .DS_Store -print0 | xargs -0 rm -f
find "$pkgroot" -name .svn -print0 | xargs -0 rm -rf
echo "Changing owner"
sudo chown -hR root:wheel "$pkgroot"
echo "Fixing permissions"
sudo ./copymodes / "$pkgroot"
rm -f "$PKGFILE"
sudo "$PACKAGEMAKER" \
    --root "$pkgroot" \
    --id "$PKGID" \
    --title "$PKGTITLE" \
    --scripts "$PKGSCRIPTS" \
    --version "$PKGVERSION" \
    --target $PKGTARGET \
    --no-recommend \
    --no-relocate \
    --out "$PKGFILE"
# --info
# --resources
echo "Changing owner of $PKGFILE"
sudo chown $USER "$PKGFILE"
echo "Removing package root"
sudo rm -rf "$pkgroot"
