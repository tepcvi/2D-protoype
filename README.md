# Likha: Ang Lahi (Prototype)

Prototype Kivy game (Python + Kivy) inspired by the study requirements:
- Endless runner (jump/slide)
- Myth-themed obstacles: `Tikbalang`, `Manananggal`, `Kapre`, `Bakunawa`
- AI-Powered Adaptive Difficulty System (AADS) using `scikit-learn` + `numpy`
- Simple rank based on score thresholds: `Alipin` (0–499), `Bathala` (>= 15000)

## Run (Desktop)

1. `cd "c:\Users\Tep\Desktop\Prototype Santle"`
2. `pip install -r requirements.txt`
3. `python main.py`

## Controls

- `JUMP` button (or `Space`)
- `SLIDE` button (or `Down Arrow`)

## What the AADS does (Prototype behavior)

During a session it tracks:
- success rate (how often you correctly jump/slide)
- average reaction time (obstacle spawn -> evaluation moment)
- death counts per obstacle type

Based on those metrics it dynamically adjusts:
- obstacle speed (`speed_multiplier`)
- obstacle spacing (`spacing_multiplier`)
- combo chance (`combo_probability`)
- obstacle type spawn weights (reduces types that kill you repeatedly)

