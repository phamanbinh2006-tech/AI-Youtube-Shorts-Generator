"""Original procedural backing track and effects. No samples/downloads/dependencies."""
import math
import random
import wave
from array import array

def make_audio(path, duration, cuts, hits):
    sr = 44100
    samples = array('f', [0.0]) * int((duration + .1) * sr)
    rng = random.Random(1907)
    tau = 2 * math.pi

    def event(start, length, kind, freq=440, gain=.1):
        offset = int(start * sr)
        for j in range(int(length * sr)):
            k = offset + j
            if k < 0 or k >= len(samples):
                continue
            t = j / sr
            if kind == 'pluck':
                env = min(1, t/.006)*math.exp(-t*13)
                v = (math.sin(tau*freq*t)+.25*math.sin(tau*freq*2*t))*env
            elif kind == 'bass':
                v = math.sin(tau*freq*t)*min(1,t/.008)*math.exp(-t*9)
            elif kind == 'kick':
                v = math.sin(tau*(48*t+1.6*(1-math.exp(-t*30))))*math.exp(-t*19)
            elif kind == 'snare':
                v = (rng.uniform(-1,1)*.75+.25*math.sin(tau*180*t))*math.exp(-t*35)
            elif kind == 'hat':
                v = rng.uniform(-1,1)*math.exp(-t*95)
            elif kind == 'pop':
                v = math.sin(tau*(650*t-1300*t*t))*math.exp(-t*26)
            else:  # short rising transition whoosh
                v = rng.uniform(-1,1)*math.sin(math.pi*t/length)**2*.7
            samples[k] += gain*v

    beat = 60/120
    melody = [76,79,83,79,74,78,81,78,72,76,79,76,74,78,81,83]
    for n in range(int(duration/beat)+1):
        t=n*beat
        event(t,.24,'kick',gain=.23)
        if n%2: event(t,.13,'snare',gain=.11)
        event(t+.25,.07,'hat',gain=.065)
        bass=[40,38,36,38][n//4%4]
        event(t,.25,'bass',440*2**((bass-69)/12),.14)
        for step in range(2):
            note=melody[(n*2+step)%len(melody)]
            event(t+step*.25,.24,'pluck',440*2**((note-69)/12),.075)
    for cut in cuts:
        event(max(0,cut-.13),.22,'whoosh',gain=.18)
        event(cut,.16,'pluck',880,.18)
        event(cut+.08,.16,'pluck',1320,.10)
    for hit in hits:
        event(hit,.13,'pop',gain=.19)
    peak=max(abs(v) for v in samples) or 1
    gain=min(1,.78/peak)
    pcm=array('h')
    for i,v in enumerate(samples[:int(duration*sr)]):
        t=i/sr
        fade=min(1,t/.015,max(0,(duration-t)/.15))
        pcm.append(round(v*gain*fade*32767))
    import sys
    if sys.byteorder != 'little': pcm.byteswap()
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())
