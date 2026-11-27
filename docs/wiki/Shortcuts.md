# Shortcuts

Press **F1** (or **Ctrl+Shift+/**) in kitty for this list over the current tab; scroll, **q** closes.
There, `★` marks a quest shortcut you haven't used yet and a green `✓` one you've earned the badge for.

## Tabs
| Keys | Does |
| --- | --- |
| **Ctrl+Shift+T** | new tab in the current folder |
| **Ctrl+Shift+W** / middle-click | close the tab (asks if something is running) |
| **Ctrl+PgUp / PgDn** | previous / next tab |
| **Alt+1 … Alt+9** | go to tab 1 … 9 |
| **Ctrl+Shift+← / →** (or **PgUp/PgDn**) | move the tab up / down the list |
| drag a tab | reorder |
| **Ctrl+Shift+R** | rename the tab |
| **Ctrl+Shift+Space** | search tabs: type part of a name, folder or number; ↑/↓, Enter goes, Esc closes; **Tab** shows only waiting / working / done tabs |
| **Ctrl+Alt+U** | go to the tab waiting for you (⚠), then the next; a failed one (✗) when none is waiting |

## Splits
| Keys | Does |
| --- | --- |
| **Ctrl+Alt+→ / ↓** | split side by side / top and bottom (same folder) |
| **Ctrl+Shift+Enter** | new pane in the current folder |
| **Ctrl+Alt+arrows** or **Ctrl+Alt+H/J/K/L** | move between panes (or just point the mouse) |
| **Ctrl+Alt+Z** | zoom one pane to full size and back |
| **Ctrl+Shift+L** | cycle layouts (splits, stack, tall, grid) |

## Text and history
| Keys | Does |
| --- | --- |
| select with the mouse | copies it; **right-click** pastes |
| **Ctrl+Shift+C / V** | copy / paste |
| **Ctrl+Shift+= / -**, **Ctrl+Shift+Backspace** | bigger / smaller / normal text |
| **Ctrl+Shift+Z / X** | jump to the previous / next command prompt |
| **Ctrl+Shift+G** | the last command's output in a pager |
| **Ctrl+Shift+H** | the whole scrollback in a pager (`/` searches, `q` quits) |
| **Ctrl+Shift+E** | open a link on screen by its hint letter |
| **Ctrl+Shift+P** then **F** | pick a file path on screen and type it |
| **Ctrl+Shift+U** | type any emoji or symbol by name |
| **Ctrl+Shift+Delete** | clear the screen and scrollback |

## Window and extras
| Keys | Does |
| --- | --- |
| **Ctrl+Shift+N** | new kitty window |
| **Ctrl+Shift+F11** | full screen |
| **Ctrl+Shift+F5** | reload kitty.conf |
| **Ctrl+Shift+F2** (or **⚙** in the sidebar) | NineLives settings: ↑/↓ choose, Enter or ←/→ change, Esc closes; the last row opens kitty.conf in your editor |
| **Ctrl+Shift+A** then **M / L / 1** | more / less see-through / solid |
| **Ctrl+Alt+M** | mute / unmute the tab sounds |
| **Ctrl+Alt+C** (or click the cat in the sidebar: its bubble opens there) | ask the cat: what needs you (Enter goes there), today's quest, a tip, joke and word of the day; →/← more, d hides one, Esc closes ([The cat](The-Cat#ask-the-cat)) |
| **F1** | this list |

## Kittens (type in any tab)
`kitten icat pic.png` shows an image, `kitten diff a b` a side-by-side diff, `kitten themes` browses
colour themes, `kitten ssh host` keeps kitty features over SSH.

## On a Mac
Not yet tried on a real Mac. kitty reads **Option as Alt** in its own shortcuts (whatever
`macos_option_as_alt` is set to), so every Alt shortcut here is Option: **Ctrl+Option+→** splits,
**Option+1** goes to tab 1, **Ctrl+Option+U** goes to the tab waiting for you, **Ctrl+Option+C** calls the cat. Function keys on a
laptop may need **Fn** (Fn+F1), or use **Ctrl+Shift+/** for this sheet. The Ctrl+Shift shortcuts work
as listed, and kitty's own ⌘ shortcuts (⌘T, ⌘W, ⌘C, ⌘V, …) keep working too.
