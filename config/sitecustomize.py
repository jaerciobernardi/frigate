"""Injeta espacos PTZ, corrige xaddr, ignora Stop e envia SOAP cru em cameras Yoosee/Leboss."""

import asyncio
import urllib.request

import onvif

PTZ_VELOCITY_SPACE = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"


def _patch_xaddrs():
    if not hasattr(onvif, "ONVIFCamera"):
        return
    orig = onvif.ONVIFCamera.update_xaddrs

    async def patched(self):
        await orig(self)
        base = f"http://{self.host}:{self.port}/onvif"
        self.xaddrs[PTZ_NS] = f"{base}/ptz_service"

    onvif.ONVIFCamera.update_xaddrs = patched


def _patch_media():
    if not hasattr(onvif, "ONVIFCamera"):
        return
    orig = onvif.ONVIFCamera.create_media_service

    async def patched(self):
        service = await orig(self)
        orig_get_profiles = service.GetProfiles

        async def get_profiles_with_ptz():
            profiles = await orig_get_profiles()
            for profile in profiles:
                ptz = getattr(profile, "PTZConfiguration", None)
                if ptz is None:
                    continue
                if getattr(ptz, "DefaultContinuousPanTiltVelocitySpace", None) is None:
                    try:
                        ptz.DefaultContinuousPanTiltVelocitySpace = {
                            "URI": PTZ_VELOCITY_SPACE,
                            "XRange": {"Min": -1.0, "Max": 1.0},
                            "YRange": {"Min": -1.0, "Max": 1.0},
                        }
                    except Exception:
                        pass
            return profiles

        service.GetProfiles = get_profiles_with_ptz
        return service

    onvif.ONVIFCamera.create_media_service = patched


def _send_raw_soap(url, body):
    req = urllib.request.Request(
        url,
        data=body.encode(),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


def _patch_ptz():
    if not hasattr(onvif, "ONVIFCamera"):
        return
    orig = onvif.ONVIFCamera.create_ptz_service

    async def patched(self):
        service = await orig(self)
        url = service.xaddr

        async def patched_move(request):
            velocity = getattr(request, "Velocity", None)
            pan_tilt = None
            if velocity is not None:
                pan_tilt = getattr(velocity, "PanTilt", None)
                if pan_tilt is None and isinstance(velocity, dict):
                    pan_tilt = velocity.get("PanTilt")
            if pan_tilt is None:
                x, y = -0.3, 0.0
            elif isinstance(pan_tilt, dict):
                x = pan_tilt.get("x", -0.3)
                y = pan_tilt.get("y", 0.0)
            else:
                x = getattr(pan_tilt, "x", -0.3)
                y = getattr(pan_tilt, "y", 0.0)

            body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:tt="http://www.onvif.org/ver10/schema"
  xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
 <soap:Body>
  <tptz:ContinuousMove>
   <tptz:ProfileToken>{request.ProfileToken}</tptz:ProfileToken>
   <tptz:Velocity>
    <tt:PanTilt x="{x}" y="{y}" space="{PTZ_VELOCITY_SPACE}"/>
   </tptz:Velocity>
  </tptz:ContinuousMove>
 </soap:Body>
</soap:Envelope>"""

            await asyncio.get_event_loop().run_in_executor(
                None, _send_raw_soap, url, body
            )
            return None

        service.ContinuousMove = patched_move

        if hasattr(service, "Stop"):
            orig_stop = service.Stop

            async def patched_stop(request):
                try:
                    await orig_stop(request)
                except Exception:
                    pass
                return None

            service.Stop = patched_stop

        return service

    onvif.ONVIFCamera.create_ptz_service = patched


try:
    _patch_xaddrs()
except Exception:
    pass
try:
    _patch_media()
except Exception:
    pass
try:
    _patch_ptz()
except Exception:
    pass