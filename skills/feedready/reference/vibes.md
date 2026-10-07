# The photographer's playbook

How a working Lightroom editor turns "make it look good" into a finished photo: pick directions, translate notes, review your own work, and know when to stop.

## Looks

A look is a starting grade. Put it in its own step: `{"name": "warm grade", "look": "warm-golden", "amount": 70}`. `amount` works like Lightroom's preset Amount: 0–200, default 100. Any `adjust` keys in the same step override the look's values. Region work (face, background, sky) always goes in separate masked steps after the look.

| look | what it does | fits | watch for |
|---|---|---|---|
| `natural` | a touch of contrast, clean whites and blacks, a little vibrance | anything; the "clean" direction | can be invisible on an already good photo |
| `bright-airy` | +0.3 EV, lifted shadows, soft contrast, pastel greens and blues | daylight portraits, food, interiors, beach | flattens night or moody light; watch the sky clipping |
| `warm-golden` | warmer white balance, rich oranges, muted blues, gentle curve | golden hour, skin-forward portraits, travel | orange skin on already warm photos; ease `amount` |
| `moody` | -0.25 EV, deep but lifted blacks, desaturated greens and blues, highlights pulled | overcast, indoor, street, forests, dramatic portraits | a dark face; always pair it with a face or subject lift |
| `film` | faded blacks, soft highlights, shifted greens, slight warmth | lifestyle, travel, casual portraits | can look muddy on low-contrast photos |
| `cinematic` | teal-shifted blues and greens, punchy oranges, contrast | city, night, landscapes with sky, travel | unnatural skin when the background is mostly orange |
| `punchy` | strong contrast, clarity, vibrance | landscapes, architecture, sport | HDR crunch on faces; mask clarity off skin |
| `mono` | black and white with skin kept bright and skies darkened | strong light and shadow, texture, emotion | flat when the photo relies on colour |

## Directions by genre

Use the `profile.genre` from `inspect`, then trust your eye over it. Offer three directions that differ in a way someone notices at thumbnail size. `board` reports `too_similar` when two tiles are close; push those apart or replace one. One direction is always the faithful "clean" version: fixes only, `natural` look.

| genre | clean | second | third | region moves that make it work |
|---|---|---|---|---|
| portrait / selfie | natural + fixes | warm-golden 60–80 (warm, soft) | moody 70–90 with a dark background (studio) or mono (editorial) | dim the background (person inverted), lift the face +0.2–0.4, eyes +0.2–0.3, heal distractions near the head |
| group | natural + fixes | bright-airy | warm-golden | even out faces (each face a radial), dim the brightest background patch |
| person in scene | natural + fixes | cinematic (travel) | film (lifestyle) | lift the person a little, keep the scene; don't let the grade swallow them |
| landscape | natural + fixes | punchy (crisp, deep sky) | moody or warm-golden depending on the light | sky highlights down, dehaze and clarity on the scenery only, a linear gradient on a bright sky |
| city / night | natural + fixes | cinematic | mono or moody | keep lights from clipping, lift shadows gently and watch the noise |
| still life / interior / food | natural + fixes | bright-airy | film or moody | clean the whites, brush away crumbs and spots, a subtle vignette |

Write each direction as a full recipe with `label` ("A · Clean") and `note` (one line in the user's language: what it feels like and what it does to this photo).

## Notes → moves

Change only what the note is about; everything else stays as it was. One notch is a visible but modest step: about 25–35% of the current value, or the step below when there's nothing to scale. Say what you read the note as when it was vague.

| the user says | do this |
|---|---|
| warmer / cooler | temp ±10 on the grade step (±6 if a face is the hero) |
| brighter / darker | exposure ±0.2 on the grade step; for "my face", ±0.15 on the face step instead |
| more / less contrast | contrast ±12; for "softer", also highlights -10 and shadows +10 |
| moodier / darker vibe | look amount +25, or switch to `moody`; background -0.2 EV; vignette -10 |
| brighter vibe / lighter / airy | exposure +0.15, shadows +15, blacks +10, or switch to `bright-airy` |
| more pop / punchier | vibrance +12, contrast +10, clarity +10 masked to the subject |
| too much / overdone / fake / HDR | look amount -30%, and halve clarity, texture and dehaze |
| more natural / less filtered | look amount -40%, or back to `natural`, and keep the region fixes |
| muted / less colour | saturation -15 or vibrance -15 |
| film / vintage / faded | add a `film` look at 60%, or lift the curve's black point to 0.06 |
| cinematic | `cinematic` look; vignette -15 |
| black and white | `mono` look; keep the region moves |
| skin looks orange / red | hsl orange sat -15 and red sat -10; ease temp on the face |
| skin looks grey / sickly | hsl orange sat +8 and lum +5; temp +5 on the face |
| face too bright / too dark | face step exposure ∓0.15 |
| I don't stand out / make me pop | background exposure -0.2 more, face +0.1, a vignette |
| background is distracting | dim it more, desaturate it (saturation -20 on the background), or heal the object |
| remove X | heal through an `object` mask on X with grow 0.004 |
| sharper / crisper | texture +10 and sharpen +20 on the subject, never on skin |
| crop tighter / looser | crop `scale` ±0.1; keep the face on the upper third |
| back to v2 | start from `v2` exactly |
| v2 but warmer | start from `v2`, then apply the move |
| between v2 and v3 | average the differing values and the look amount |
| I don't like it / something's off | show the board of versions plus one fresh direction; ask which is closest |

## Self-review checklist

Run it on every version before the user sees it. `critique` measures some of it; your eye covers the rest.

1. **Brief.** Does it hit the vibe the user asked for? Would you post it?
2. **Where the eye lands.** The hero (face or subject) is the brightest, most contrasty and most saturated area that matters. Edges and corners don't pull the eye away.
3. **Skin.** It reads as skin: not orange, grey, green or plastic. Skin hue sits around 10–35°.
4. **Light.** No new clipping, no grey blacks unless the look is faded, and the sky keeps its tone.
5. **Edges of masks.** No halo around the person or the horizon, and no hard seam where a gradient ends.
6. **Restraint.** No HDR crunch, and no step that does nothing (`impact: none`).
7. **Frame.** The crop suits the destination, the horizon is level, and nothing important is cut at a joint.

## When to stop

- **The user is satisfied:** "ship it", "done", "perfect", "love it". Export that version.
- **You are satisfied:** the critique verdict is `clean`, the vibe lands, and anything left is a taste swap rather than an improvement. Say so plainly ("This is where I'd stop: v3."), export it, and leave the door open.
- **It isn't converging:** after 5 rounds of notes, show the versions board and ask which is closest, then narrow from there.
