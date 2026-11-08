"""Non-secret explanations for hosted-app transport failures."""
import socket
import ssl
import urllib.error


def reason(error):
    if isinstance(error,urllib.error.HTTPError):
        if error.code in (401,403):return 'Hosted app denied connector access; check pairing/configuration privately'
        if error.code in (502,503,504):return 'Hosted app is starting, redeploying or temporarily unavailable'
        return 'Hosted app returned HTTP '+str(error.code)
    cause=error.reason if isinstance(error,urllib.error.URLError) else error
    if isinstance(cause,ssl.SSLCertVerificationError):return 'HTTPS certificate verification failed; check Windows date and trusted certificates (do not disable TLS verification)'
    if isinstance(cause,socket.gaierror):return 'Windows could not resolve the hosted app hostname; check DNS/internet'
    if isinstance(cause,(TimeoutError,socket.timeout)):return 'Hosted app connection timed out; check Render status and Windows internet'
    if isinstance(cause,ConnectionRefusedError):return 'Hosted app connection was refused'
    if isinstance(cause,ConnectionResetError):return 'Hosted app connection was reset'
    return 'Hosted app network request failed ('+type(cause).__name__+'); run the HTTPS health check on Windows'
