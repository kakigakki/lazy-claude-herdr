# Regenerate the herdr popup GIF:  vhs demo/herdr.tape   (run from the repository root)
# Runs an isolated herdr session ("lch-demo") on fixture data from demo/make_demo.py.
# Afterwards: herdr session stop lch-demo && herdr session delete lch-demo

Output demo/herdr.gif

Require herdr
Require fzf
Set Shell "bash"
Set FontSize 14
Set Width 1800
Set Height 680
Set Padding 12
Set Theme "Catppuccin Mocha"
Set TypingSpeed 70ms

Hide
Type "rm -rf /tmp/lch-demo && python3 demo/make_demo.py /tmp/lch-demo >/dev/null && sh demo/herdr-demo.sh /tmp/lch-demo"
Enter
Sleep 12s
Show

Sleep 1.5s
# open the popup from anywhere: prefix + f
Ctrl+B
Type "f"
Sleep 3s
# a live session: Enter jumps to the pane it runs in, in another space
Type "coupon"
Sleep 1.5s
Enter
Sleep 3s

# a stopped session: Enter splits a pane in its own space and resumes it
Ctrl+B
Type "f"
Sleep 2.5s
Type "3"
Sleep 2s
Enter
Sleep 4s

# sort by environment, then close
Ctrl+B
Type "f"
Sleep 2s
Ctrl+S
Sleep 2.5s
Escape
Sleep 1.5s
