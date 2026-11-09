--!nonstrict
-- Phone-style media card, using the desktop's live Noctalia palette.
local player = noctalia.state.get("player")
local panelIsOpen = false
local commandSerial = 0
local library = { authorized = false, albums = {} }
local loadingLibrary = false
local pendingSeek = nil
local render
local menu = nil
local menuItems = {}
local menuLoading = false
local menuQuery = ""
local menuError = ""
local actionMessage = ""
local actionBusy = false
local menuSerial = 0

local function request(action)
  commandSerial += 1
  noctalia.state.set("command", {
    action = action,
    nonce = tostring(noctalia.nowMs()) .. ":" .. tostring(commandSerial),
  })
end

local function quickControl(action, identifier)
  if actionBusy then return end
  actionBusy = true
  actionMessage = "Working…"
  if panelIsOpen then render() end
  local args = { "spotify-quick-control", action, "--json" }
  if identifier ~= nil then table.insert(args, identifier) end
  noctalia.runAsync(args, function(result)
    actionBusy = false
    local ok, decoded = pcall(noctalia.json.decode, result.stdout or "")
    if ok and type(decoded) == "table" then
      actionMessage = decoded.message ~= "" and decoded.message or (decoded.ok and "Done" or "Request failed")
    else
      actionMessage = "Could not complete the request. Check your Spotify connection."
    end
    if panelIsOpen then render() end
  end)
end

local function openMenu(kind)
  menu = kind
  menuQuery = ""
  menuItems = {}
  menuError = ""
  actionMessage = ""
  menuLoading = true
  menuSerial += 1
  local serial = menuSerial
  render()
  noctalia.runAsync({ "spotify-quick-control", "list-" .. kind, "--json" }, function(result)
    if serial ~= menuSerial or not panelIsOpen then return end
    menuLoading = false
    local ok, decoded = pcall(noctalia.json.decode, result.stdout or "")
    if ok and type(decoded) == "table" and decoded.ok then
      menuItems = decoded.items or {}
      menuError = decoded.message or ""
    else
      menuError = ok and type(decoded) == "table" and decoded.message or "Could not load your Spotify library."
    end
    render()
  end)
end

local function menuView()
  local labels = { albums = "Your albums", liked = "Liked songs", devices = "Spotify devices" }
  local rows = {}
  for _, value in ipairs(menuItems) do
    local item = value
    local haystack = string.lower(item.name .. " " .. (item.detail or ""))
    if menuQuery == "" or string.find(haystack, string.lower(menuQuery), 1, true) then
      table.insert(rows, ui.button({ key = menu .. "-" .. item.id,
        text = item.name .. ((item.detail or "") ~= "" and (" · " .. item.detail) or ""),
        glyph = menu == "albums" and "disc" or (menu == "liked" and "heart" or "devices"),
        variant = "ghost", width = 364, controlSize = "sm", enabled = not actionBusy,
        onClick = function()
          if item.restricted then
            actionMessage = "Spotify restricts this speaker. Use Spotify/Sonos, or choose another device."
            render()
          else
            quickControl(menu == "albums" and "play-album" or (menu == "liked" and "play-track" or "connect-device"), item.id)
          end
        end }))
    end
  end
  if #rows == 0 then
    table.insert(rows, ui.label({ text = menuLoading and "Loading…" or (menuError ~= "" and menuError or "No matching items"),
      maxWidth = 364, maxLines = 3, color = "on_surface_variant", fontSize = 12 }))
  end
  return ui.column({ gap = 8, height = 164, align = "stretch" }, {
    ui.row({ align = "center", justify = "space_between" }, {
      ui.button({ text = "Back", glyph = "arrow-left", variant = "ghost", controlSize = "sm",
        onClick = function() menu = nil; menuSerial += 1; render() end }),
      ui.label({ text = labels[menu], fontSize = 13, fontWeight = "bold", color = "on_surface" }),
      ui.button({ glyph = "refresh", variant = "ghost", controlSize = "sm", enabled = not menuLoading,
        onClick = function() openMenu(menu) end }),
    }),
    ui.input({ key = "search-" .. menu, value = menuQuery, placeholder = "Search…", width = 372,
      onChange = function(text) menuQuery = tostring(text); render() end }),
    ui.scroll({ key = "items-" .. menu, flexGrow = 1, gap = 3 }, rows),
  })
end

local function formatTime(microseconds)
  local seconds = math.max(0, math.floor((tonumber(microseconds) or 0) / 1000000))
  return string.format("%d:%02d", math.floor(seconds / 60), seconds % 60)
end

local function outputControls()
  noctalia.runAsync({"noctalia", "msg", "panel-open", "control-center", "audio"})
end

local function artwork(media)
  local path = tostring(media.artPath or "")
  if path ~= "" and noctalia.fileExists(path) then
    return ui.image({ key = "track-art", path = path, width = 56, height = 56, radius = 10, fit = "contain" })
  end
  return ui.column({ width = 56, height = 56, radius = 10, fill = "surface_container",
    align = "center", justify = "center" }, {
    ui.glyph({ name = "music", size = 26, color = "primary" }),
  })
end

local function albumRow()
  local children = {}
  for _, album in ipairs(library.albums or {}) do
    local item = album
    local content
    if item.cover ~= nil and item.cover ~= "" and noctalia.fileExists(item.cover) then
      content = ui.image({ path = item.cover, width = 80, height = 80, radius = 12, fit = "contain" })
    else
      content = ui.column({ width = 80, height = 80, radius = 12, fill = "surface_container",
        align = "center", justify = "center", gap = 4 }, {
        ui.glyph({ name = "disc", size = 28, color = "primary" }),
        ui.label({ text = item.name, fontSize = 10, maxWidth = 72, maxLines = 2,
          textAlign = "center", color = "on_surface_variant" }),
      })
    end
    table.insert(children, ui.column({ key = "album-" .. item.id, width = 80, height = 80,
      tooltip = "Play " .. item.name, onClick = function() quickControl("play-album", item.id) end }, { content }))
  end
  if #children > 0 then
    return ui.row({ gap = 12, align = "center", justify = "center" }, children)
  end
  if not library.authorized then
    return ui.column({ height = 80, gap = 8, align = "center", justify = "center" }, {
      ui.label({ text = "Sign in to show your saved albums", fontSize = 12, color = "on_surface_variant" }),
      ui.button({ text = "Connect Spotify", glyph = "brand-spotify", variant = "ghost", controlSize = "sm",
        onClick = function()
          noctalia.runAsync({"spotify-island", "setup-window"}, function(result)
            if result.exitCode ~= 0 then
              actionMessage = "Run spotify-island setup --account in a terminal, or set your terminal in spotify-island/config.toml."
              render()
            end
          end)
        end }),
    })
  end
  return ui.column({ height = 80, align = "center", justify = "center" }, {
    ui.label({ text = loadingLibrary and "Loading your albums…" or (library.error or "Save albums in Spotify for quick access"),
      fontSize = 12, color = "on_surface_variant", maxWidth = 350, maxLines = 2, textAlign = "center" }),
  })
end

render = function()
  local media = type(player) == "table" and player or {}
  local available = type(player) == "table" and tostring(media.title or "") ~= ""
  local isSpotify = string.find(string.lower(tostring(media.busName or "")), "spotify") ~= nil
  local title = available and tostring(media.title) or "Nothing playing"
  local artist = available and tostring(media.artist or "") or "Your music, ready when you are"
  if available and media.canControl == false then artist ..= " • controls restricted by Spotify" end
  local controllable = available and media.canControl ~= false
  local lengthUs = tonumber(media.lengthUs) or 0
  local positionUs = tonumber(media.positionUs) or 0
  local progress = lengthUs > 0 and math.max(0, math.min(1, positionUs / lengthUs)) or 0

  panel.render(ui.column({ padding = 20, gap = 12, align = "stretch", fill = "surface", radius = 24 }, {
    -- Artwork and metadata above the timeline, as in the supplied reference.
    ui.row({ gap = 12, align = "center" }, {
      artwork(media),
      ui.column({ width = 232, gap = 5 }, {
        ui.label({ text = title, fontSize = 18, fontWeight = "bold", color = "on_surface", maxLines = 1, maxWidth = 232 }),
        ui.label({ text = artist, fontSize = 13, color = "on_surface_variant", maxLines = 1, maxWidth = 232 }),
      }),
      ui.glyph({ name = "brand-spotify", size = 22, color = "primary" }),
    }),
    ui.column({ gap = 0 }, {
      ui.slider({ key = "track-seek", min = 0, max = 1, step = 0.001, value = progress,
        width = 372, controlSize = "sm", enabled = controllable and media.canSeek ~= false and lengthUs > 0,
        -- onChange carries the value; onDragEnd is an argument-free event.
        onChange = function(value)
          local fraction = tonumber(value)
          if fraction == nil or fraction ~= fraction then return end
          pendingSeek = {
            trackKey = media.trackKey,
            positionUs = math.floor(math.max(0, math.min(1, fraction)) * lengthUs),
          }
        end,
        onDragEnd = function()
          local seek = pendingSeek
          pendingSeek = nil
          -- A track change during dragging must not seek the next song.
          if seek == nil or type(player) ~= "table" or seek.trackKey ~= player.trackKey then return end
          noctalia.runAsync({"busctl", "--user", "call", "dev.noctalia.Mpris", "/dev/noctalia/Mpris",
            "dev.noctalia.Mpris", "SetPositionPlayer", "sx", player.busName, tostring(seek.positionUs)})
        end }),
      ui.row({ justify = "space_between", align = "center" }, {
        ui.label({ text = formatTime(positionUs), fontSize = 11, color = "on_surface_variant" }),
        ui.label({ text = formatTime(lengthUs), fontSize = 11, color = "on_surface_variant" }),
      }),
    }),
    -- Symmetric controls with the play/pause action as the main visual target.
    ui.row({ gap = 18, align = "center", justify = "center" }, {
      ui.button({ glyph = "cast", glyphSize = 22, variant = "ghost", width = 34, height = 40,
        tooltip = "Speakers, headphones and volume", onClick = outputControls }),
      ui.button({ glyph = "player-skip-back-filled", glyphSize = 26, variant = "ghost", width = 40, height = 44,
        enabled = controllable and media.canGoPrevious ~= false, tooltip = "Previous track", onClick = function() request("previous") end }),
      ui.column({ width = 56, height = 56, radius = 28, fill = "primary", align = "center", justify = "center",
        opacity = controllable and 1.0 or 0.45, tooltip = media.playing and "Pause" or "Play",
        onClick = function() if controllable then request("toggle") end end }, {
        ui.glyph({ name = media.playing and "player-pause-filled" or "player-play-filled", size = 28, color = "on_primary" }),
      }),
      ui.button({ glyph = "player-skip-forward-filled", glyphSize = 26, variant = "ghost", width = 40, height = 44,
        enabled = controllable and media.canGoNext ~= false, tooltip = "Next track", onClick = function() request("next") end }),
      ui.button({ glyph = "circle-plus", glyphSize = 24, variant = "ghost", width = 34, height = 40,
        enabled = available and isSpotify, tooltip = "Add to Liked Songs", onClick = function() quickControl("like") end }),
    }),
    menu ~= nil and menuView() or albumRow(),
    ui.row({ gap = 12, align = "center", justify = "center" }, {
      ui.button({ text = "Albums", glyph = "disc", variant = "ghost", controlSize = "sm",
        onClick = function() openMenu("albums") end }),
      ui.button({ text = "Liked songs", glyph = "heart", variant = "ghost", controlSize = "sm",
        onClick = function() openMenu("liked") end }),
      ui.button({ text = "Devices", glyph = "devices", variant = "ghost", controlSize = "sm",
        onClick = function() openMenu("devices") end }),
    }),
    ui.label({ text = actionMessage, fontSize = 11, color = "on_surface_variant", maxWidth = 372, maxLines = 3 }),
  }))
end

noctalia.state.watch("player", function(value)
  player = value
  if panelIsOpen then render() end
end)

function onOpen()
  panelIsOpen = true
  menu = nil
  menuSerial += 1
  actionMessage = ""
  player = noctalia.state.get("player")
  noctalia.state.set("panel-open", true)
  loadingLibrary = true
  render()
  noctalia.runAsync({"spotify-quick-control", "snapshot"}, function(result)
    loadingLibrary = false
    if result.exitCode == 0 then
      local ok, decoded = pcall(noctalia.json.decode, result.stdout)
      if ok and type(decoded) == "table" then library = decoded end
    end
    if panelIsOpen then render() end
  end)
end

-- Allow opening a specific embedded view through the standard plugin IPC.
function onIpc(event, payload)
  if event == "page" and (payload == "albums" or payload == "liked" or payload == "devices") then
    openMenu(payload)
  end
end

function onClose()
  menuSerial += 1
  pendingSeek = nil
  panelIsOpen = false
  noctalia.state.set("panel-open", false)
end

function onExit()
  noctalia.state.set("panel-open", false)
end

render()
