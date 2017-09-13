# Kodi

Requirements
============
You only need one or more Kodi (12 a.k.a. Frodo or above) with
System-Settings-Service "Allow programs on other systems to control Kodi" enabled.

Configuration
=============

## plugin.conf

<pre>
[kodi]
    class_name = Kodi
    class_path = plugins.kodi
</pre>

## items.conf
<pre>
[living]
    [[kodi]]
        type = str
        kodi_host = kodi.home
        # kodi_port = 9090
        kodi_listen = state
        [[[title]]]
            type = str
            kodi_listen = title
        [[[media]]]
            type = str
            kodi_listen = media
        [[[volume]]]
            type = num
            kodi_listen = volume
            kodi_send = volume
        [[[mute]]]
            type = bool
            kodi_listen = mute
            kodi_send = mute
</pre>

### kodi_host
This attribute is mandatory. You have to provide the IP address or host name of the XBMC system.

### kodi_port
You could specify a port to connect to. By default port 9090 is used.

### kodi_listen
You could assign the following values to `kodi_listen`:

   * `volume` a numeric value (0 -100)
   * `mute` a bool flag
   * `title` a string with the name of the movie, song or picture
   * `media` a string with the current media type (Video, Audio, Picture)
   * `state` current state as string (Menu, Playing, Pause)

### kodi_send
The following `kodi_send` attributes could be defined to send changes to the system:

   * `volume` a numeric value (0 -100)
   * `mute` a bool flag


## logic.conf

Functions
=========
This plugin provides the function to send notification messages to kodi. 
`notify_all(title, message, picture)` to send the notification to all kodi systems and extends the item with the notify method.
The picture attribute is optional.

<pre>
sh.kodi.notify_all('Phone', 'Sister in law calling', 'http://smarthome.local/img/phone.png') 
# or for a dedicated kodi
sh.living.kodi.notify('Door', 'Ding Dong')
</pre>
