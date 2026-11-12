#!/bin/sh
# Build the ext2 disks of the fi2 K1 item-5 tests with a real mke2fs, inside
# a throw-away Alpine container (scripts/verify_kernel_k5.mjs runs it):
#
#   docker run --rm --name fi2k-mkext2 -v <dir>:/work alpine:3.20 sh /work/k5_ext2_images.sh
#
# <dir> holds a copy of this script; the images are written next to it.
#
# clean.img   32 MiB, 1 KiB blocks, `mke2fs -t ext2` defaults (sparse_super,
#             resize_inode, dir_index, filetype, large_file, ext_attr), filled
#             with `-d`: a 300 KiB file (direct, single and double indirect
#             blocks), a file with a hard link, a directory of 300 entries
#             (more than 12 blocks) and a small file. The kernel writes and
#             removes on it; `e2fsck -fn` must find it clean afterwards.
# crafted.img the same layout plus a 7 MiB filler that fills group 0, then
#             damaged with debugfs: `xlink` shares its first block with
#             `victim`; `evil` points at group 1's backup superblock; the
#             backup superblock, descriptor and reserved descriptor blocks of
#             group 1 are marked free in the bitmap.
set -e
apk add --no-cache e2fsprogs e2fsprogs-extra >/dev/null
cd /work
rm -rf pop clean.img crafted.img
mkdir -p pop/bigdir
head -c 307200 /dev/urandom > pop/big
printf 'hard link content\n' > pop/link1
ln pop/link1 pop/link2
printf 'small file\n' > pop/small
i=1
while [ $i -le 300 ]; do
  : > "pop/bigdir/entry-with-a-reasonably-long-name-$(printf %04d $i)"
  i=$((i + 1))
done
mke2fs -q -F -t ext2 -b 1024 -L k5clean -d pop clean.img 32M
e2fsck -fn clean.img > clean.fsck.txt 2>&1 || true

head -c 6815744 /dev/zero > pop/filler
yes victim | head -c 1024 > pop/victim
yes xlink | head -c 1024 > pop/xlink
printf 'evil\n' > pop/evil
mke2fs -q -F -t ext2 -b 1024 -L k5craft -d pop crafted.img 32M
VB=$(debugfs -R "bmap /victim 0" crafted.img 2>/dev/null)
debugfs -w -R "sif /xlink block[0] $VB" crafted.img 2>/dev/null
debugfs -w -R "sif /evil block[0] 8193" crafted.img 2>/dev/null
RES=$(dumpe2fs -h crafted.img 2>/dev/null | sed -n 's/^Reserved GDT blocks: *//p')
debugfs -w -R "freeb 8193 $((2 + RES))" crafted.img 2>/dev/null
# Mark the rest of group 0 used, so the kernel's next allocations come from
# group 1, where the backup superblock and descriptor blocks now look free.
G0FREE=$(dumpe2fs crafted.img 2>/dev/null | sed -n '/^Group 0:/,/^Group 1:/s/^  Free blocks: \([0-9]*\)-8192.*/\1/p')
debugfs -w -R "setb $G0FREE $((8193 - G0FREE))" crafted.img 2>/dev/null
{
  echo "victim_block=$VB"
  echo "reserved_gdt=$RES"
  dumpe2fs crafted.img 2>/dev/null | sed -n '/^Group 0:/,/^Group 2:/p'
  dumpe2fs -h clean.img 2>/dev/null | grep -iE 'features|block count|blocks per group|reserved gdt|inode size'
} > layout.txt
e2fsck -fn crafted.img > crafted.fsck.txt 2>&1 || true
rm -rf pop
echo done
