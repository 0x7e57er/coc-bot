"""Click points and read regions, measured on the 1920x1080 base screen (see space.py).

    point("home.attack")   -> (x, y) in the current game space, pinned to its screen edge
    region("home.gold")    -> (x, y, w, h) in the current game space

Points and regions of the army screen (a full-screen window) are placed like that window instead
(space.window_point): on BlueStacks it is drawn smaller, around the screen centre.
"""

from .space import space

POINTS = {
    "home.attack": [105, 975],
    "home.settings": [85, 100],          # profile picture (top left): Settings is a tab of the profile menu
    "home.safe": [1830, 420],            # home village: forest edge (NOT 330: that is the gems counter -> Shop)
    "bb.safe": [1640, 470],              # Builder Base: forest right of the island (NOT the top: the boat is there)
    "popup.shield_continue": [960, 902],
    "popup.close_x": [1615, 155],        # the X of big popups (daily reward, offers)
    "shop.close": [1857, 66],
    "attack_menu.close": [1725, 665],    # tapping the village beside the menu closes it (right of an event panel
                                         # such as Treasure Hunt, which covers the old spot [1400, 540])
    "attack_menu.edit_army": [190, 1030],   # Battle menu: Edit Army (the army screen; there is no army button)
    "army.close": [1762, 147],
    "army.recipes_arrow": [1140, 155],   # Saved Recipes drop-down arrow in the army screen
    "scout.next": [1775, 820],
    "scout.end_battle": [115, 848],
    "profile.settings_tab": [1475, 127],   # the Settings tab of the profile menu
    "settings.switch_id": [1237, 228],
    "settings.close": [1620, 122],
    "sid.close": [1866, 53],
    "sid.page_from": [1643, 1031],       # one drag 1031 -> 390 in 0.5 s = exactly 4 accounts down
    "sid.page_to": [1643, 390],
    "sid.page_up_from": [1643, 545],     # upwards the drag must start inside the list (about 3 accounts)
    "sid.page_up_to": [1643, 1078],
    "home.chat": [85, 545],              # clan chat (shield with a speech bubble, left)
    "chat.close": [655, 497],
    "chat.scroll_from": [300, 300],      # a swipe down in the chat = older messages
    "chat.scroll_to": [300, 760],
    "donate.close": [1860, 675],         # scenery right of the donate window (taps outside it close it)
    "dialog.cancel": [785, 668],         # orange Cancel of a two-button confirmation
    "request.cancel": [768, 722],        # Cancel of the request window
    "build.close": [1888, 34],           # X of the Build side panel
    "top.builders_menu": [1815, 975],    # Build button (bottom right)
}

REGIONS = {
    "home.gold": [1600, 28, 245, 40],
    "home.elixir": [1600, 90, 245, 40],
    "home.dark": [1680, 152, 165, 38],
    "scout.gold": [78, 112, 230, 32],
    "scout.elixir": [78, 160, 230, 32],
    "scout.dark": [78, 208, 230, 32],
    "home.player_name": [150, 66, 320, 40],   # in-game name next to the Town Hall picture
    "army.recipe_list": [865, 210, 550, 560],   # the Saved Recipes drop-down list
}


WINDOW = ("army.",)        # names of points / regions inside a full-screen window


def point(name):
    """A click point in the current game space (pinned to its screen edge, or placed in its window)."""
    if name.startswith(WINDOW):
        return space.window_point(*POINTS[name])
    return space.point(*POINTS[name])


def region(name):
    """A read region in the current game space (pinned to its screen edge, or placed in its window)."""
    if name.startswith(WINDOW):
        return space.window_region(*REGIONS[name])
    return space.region(*REGIONS[name])
