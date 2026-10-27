from __future__ import annotations
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
import cv2
import numpy as np
from .virtual_output import VirtualOutput
from .gesture import HoldGate
from .gesture_guides import guide_for
from .scene import Frame, Scene
from .vision import Detector, Segmenter
from .effects import Silhouette, TeleportEffect
from .effect_catalog import EFFECTS
from .background import LiveBackground
from .paths import resource_root
from .platform_support import IS_MAC, camera_apis

@dataclass(frozen=True)
class Settings:
    camera: int = 0
    camera_backend: int | None = None
    width: int = 1280
    height: int = 720
    fps: int = 30
    hold: float = 1.0
    virtual: str = 'obs'
    effect: str = 'goku'
    dynamic_background: bool = False

class Engine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dynamic_background = settings.dynamic_background
        self.effect_mode = settings.effect
        self.preview_revision = 0
        self.stop = Event()
        self.commands: Queue[str] = Queue()
        self.lock = Lock()
        self.raw: tuple[float, Frame] | None = None
        self.observation = (0.0, False, -1)
        self.observation_effect = settings.effect
        self.gesture_progress = 0.0
        self.gesture_release_required = False
        self.silhouette: Silhouette | None = None
        self.need_silhouette = Event()
        self.disappearances: Queue[tuple[float,bool]] = Queue()
        self.virtual_active = False
        self.background_status = ''
        self.preview: Frame | None = None
        self.message = 'Abrindo webcam…'
        self.phase = 'opening'
        self.hidden = False
        self.virtual_status = 'Saída virtual desligada'
        self.gesture_error = ''
        self.effect_error = ''
        self.vision_hint = 'Preparando reconhecimento…'
        self.fps = 0.0
        self.progress = 0.0
        self.running = True
        self.thread = Thread(target=self._run, daemon=True, name='video')
        self.thread.start()

    def snapshot(self) -> tuple[Frame | None, str, float]:
        with self.lock:
            notes = [self.message, self.virtual_status, self.gesture_error, self.effect_error, self.background_status]
            return (None if self.preview is None else self.preview.copy(),
                    '\n'.join(note for note in notes if note), self.fps)

    def _set_message(self, text: str) -> None:
        with self.lock:
            self.message = text

    def _inference(self) -> None:
        detector: Detector | None = None
        segmenter: Segmenter | None = None
        folder=resource_root()/'models'
        try:
            try:
                detector=Detector(folder)
            except Exception as error:
                self.gesture_error=f'Gesto indisponível: {error}. Use o botão Ativar efeito.'
            segment_attempted=False
            if self.effect_mode in EFFECTS or self.dynamic_background:
                segment_attempted=True
                try:
                    segmenter=Segmenter(folder)
                except Exception as error:
                    self.effect_error=f'Recorte indisponível: {error}. Usando fundo salvo e corte instantâneo.'
            previous=-1.0
            previous_mask=-1.0
            while not self.stop.is_set():
                began=monotonic()
                if not segment_attempted and (self.effect_mode in EFFECTS or self.dynamic_background):
                    segment_attempted=True
                    try: segmenter=Segmenter(folder)
                    except Exception as error: self.effect_error=f'Recorte indisponível: {error}. Usando fundo estático.'
                with self.lock:
                    raw=self.raw
                if raw is not None and raw[0]>previous:
                    previous=raw[0]
                    if detector is not None:
                        try:
                            mode=self.effect_mode
                            matched,count=detector.detect(raw[1],raw[0],mode)
                            with self.lock:
                                self.observation=(raw[0],matched,count)
                                self.observation_effect=mode
                                self.gesture_progress=detector.progress
                                self.vision_hint=detector.hint
                        except Exception as error:
                            self.gesture_error=f'Falha no gesto: {error}. Use os controles manuais.'
                            detector.close()
                            detector=None
                            with self.lock:
                                self.observation=(0.0,False,-1)
                    if segmenter is not None and self.need_silhouette.is_set() and raw[0]-previous_mask>=0.16:
                        try:
                            silhouette=segmenter.capture(raw[1],raw[0])
                            previous_mask=raw[0]
                            with self.lock:
                                self.silhouette=silhouette
                        except Exception as error:
                            self.effect_error=f'Recorte indisponível: {error}. Será usado corte instantâneo.'
                            segmenter.close()
                            segmenter=None
                rate=30 if guide_for(self.effect_mode).motion else 15
                self.stop.wait(max(0.001,1/rate-(monotonic()-began)))
        finally:
            if detector is not None: detector.close()
            if segmenter is not None: segmenter.close()

    def _open_capture(self) -> cv2.VideoCapture:
        # A named DirectShow index must not be reused against a different backend.
        backends=(self.settings.camera_backend,) if self.settings.camera_backend is not None else camera_apis()
        # macOS asks for camera permission on the first attempt and that attempt fails; retry once.
        attempts=[backend for backend in backends for _ in range(2 if IS_MAC else 1)]
        for attempt,backend in enumerate(attempts):
            if attempt and IS_MAC:
                self.stop.wait(1.5)
            capture=cv2.VideoCapture(self.settings.camera,backend)
            if capture.isOpened():
                if not IS_MAC:  # AVFoundation chooses the pixel format itself.
                    capture.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
                capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.settings.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.settings.height)
                capture.set(cv2.CAP_PROP_FPS,self.settings.fps)
                capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
                return capture
            capture.release()
        if IS_MAC:
            raise RuntimeError('Webcam indisponível. Libere a câmera para o Terminal em Ajustes do Sistema → '
                               'Privacidade e Segurança → Câmera, feche outros apps que a usam e tente de novo.')
        raise RuntimeError('Webcam indisponível. Atualize a lista, confira permissões e feche outras aplicações que a utilizam.')

    def _open_virtual(self,width:int,height:int) -> VirtualOutput | None:
        if self.settings.virtual=='off': return None
        try:
            virtual=VirtualOutput(width,height,self.settings.fps,self.settings.virtual)
            self.virtual_status=f'Saída: {virtual.device} · {width} × {height}'
            return virtual
        except (RuntimeError,OSError,ValueError) as error:
            self.virtual_status=f'Saída virtual indisponível: {error}. Instale/libere o driver e reconecte a saída.'
            return None

    def _run(self) -> None:
        capture:cv2.VideoCapture | None=None
        virtual:VirtualOutput | None=None
        inference:Thread | None=None
        scene=Scene()
        adaptive=LiveBackground()
        if scene.background is not None: adaptive.reset(scene.background)
        announced_hidden=False
        gate=HoldGate(self.settings.hold)
        effect:TeleportEffect | None=None
        requested:float | None=None
        calibration:float | None=None
        samples:list[Frame]=[]
        calibration_face=False
        previous_observation=0.0
        virtual_attempted=False
        failed_reads=0
        measured=monotonic()
        count=0
        try:
            capture=self._open_capture()
            inference=Thread(target=self._inference,daemon=True,name='recognition')
            inference.start()
            self.phase='uncalibrated'
            self._set_message('Webcam aberta. Capture e confirme o fundo vazio.')
            while not self.stop.is_set():
                tick=monotonic()
                ok,frame=capture.read()
                if not ok or frame is None:
                    failed_reads+=1
                    gate.reset()
                    self.progress=0
                    self._set_message('Falha de leitura. Tentando recuperar a webcam…')
                    if failed_reads>=15:
                        raise RuntimeError('Webcam desconectada. Pare e inicie novamente para reconectar.')
                    self.stop.wait(0.05)
                    continue
                failed_reads=0
                now=monotonic()
                with self.lock:
                    self.raw=(now,frame)
                    observed_at,matched,faces=self.observation
                    observed_effect=self.observation_effect
                    motion_progress=self.gesture_progress
                    silhouette=self.silhouette
                height,width=frame.shape[:2]
                if not virtual_attempted:
                    virtual=self._open_virtual(width,height)
                    virtual_attempted=True
                    self.virtual_active=virtual is not None
                while True:
                    try: command=self.commands.get_nowait()
                    except Empty: break
                    gate.reset()
                    previous_observation=now
                    if command=='restore':
                        effect=None
                        requested=None
                        scene.restore()
                        scene.pending=None
                        calibration=None
                        self._set_message('Imagem ao vivo restaurada.')
                    elif command=='calibrate':
                        effect=None
                        requested=None
                        calibration=now
                        samples.clear()
                        calibration_face=False
                        scene.pending=None
                    elif command=='confirm':
                        try:
                            scene.confirm()
                            adaptive.reset(scene.background)
                            self._set_message('Fundo confirmado. Prepare o gesto indicado para o efeito selecionado.')
                        except ValueError as error: self._set_message(str(error))
                    elif command=='toggle' and calibration is None and scene.pending is None and effect is None and requested is None:
                        if scene.background is None:
                            self._set_message('Capture e confirme o fundo primeiro.')
                        else: requested=now
                    elif command in ('background:live','background:static'):
                        self.dynamic_background=command=='background:live'
                        if scene.background is not None: adaptive.reset(scene.background)
                        self._set_message('Fundo em movimento ativado.' if self.dynamic_background else 'Fundo estático ativado.')
                    elif command.startswith('effect:'):
                        mode=command.partition(':')[2]
                        if mode in EFFECTS or mode=='instant':
                            self.effect_mode=mode
                            self._set_message('Efeito selecionado para a próxima ativação.')
                    elif command=='virtual':
                        if virtual is not None: virtual.close()
                        virtual=self._open_virtual(width,height)
                        self.virtual_active=virtual is not None
                if calibration is not None:
                    elapsed=now-calibration
                    self._set_message(f'Saia do enquadramento. Capturando em {max(0,4-elapsed):.1f} s…')
                    if elapsed>=3.3:
                        samples.append(frame.copy())
                        samples=samples[-16:]
                        if now-observed_at<0.3 and faces>0: calibration_face=True
                    if elapsed>=4:
                        try:
                            if calibration_face: raise ValueError('Rosto detectado. Repita com o cenário vazio.')
                            scene.propose(samples)
                            self._set_message('Confira o fundo na prévia. Se estiver vazio, confirme abaixo.')
                        except ValueError as error: self._set_message(str(error))
                        samples.clear()
                        calibration=None
                    gate.reset()
                elif scene.pending is None and scene.background is not None and effect is None and requested is None:
                    if now-observed_at>0.3 or observed_effect!=self.effect_mode:
                        gate.reset()
                    elif observed_at>previous_observation:
                        previous_observation=observed_at
                        if guide_for(self.effect_mode).motion:
                            if matched: requested=now
                        elif guide_for(self.effect_mode).kind!='manual' and gate.update(matched,observed_at): requested=now
                else:
                    gate.reset()
                guide=guide_for(self.effect_mode)
                self.gesture_release_required=(not guide.motion and guide.kind!='manual' and matched and not gate.armed
                    and now-observed_at<.3 and observed_effect==self.effect_mode and calibration is None
                    and scene.pending is None and scene.background is not None and effect is None and requested is None)
                self.progress=(motion_progress if guide.motion and now-observed_at<.3 and observed_effect==self.effect_mode else 0) if guide.motion else gate.progress
                if requested is not None:
                    wants_goku=self.effect_mode in EFFECTS and not self.effect_error
                    fresh=(silhouette is not None and now-silhouette.captured_at<=0.35 and silhouette.frame.shape==frame.shape)
                    if wants_goku and not fresh and now-requested<0.8:
                        self._set_message('Preparando recorte para o efeito…')
                    else:
                        target=not scene.hidden
                        if wants_goku and fresh and silhouette is not None:
                            try:
                                effect_class=EFFECTS[self.effect_mode]
                                effect=effect_class(silhouette,target,now)
                                scene.toggle()
                                self._set_message('Efeito em andamento…')
                            except ValueError as error:
                                self._set_message(str(error))
                        else:
                            scene.toggle()
                            self._set_message('Corte instantâneo aplicado: recorte indisponível.' if wants_goku else ('Desaparecido.' if scene.hidden else 'Imagem ao vivo.'))
                        requested=None
                        gate.reset()
                try:
                    background=scene.background
                    if self.dynamic_background and background is not None and calibration is None and scene.pending is None:
                        if silhouette is not None and now-silhouette.captured_at<=0.35:
                            adaptive.observe(silhouette.frame,silhouette.mask,silhouette.captured_at)
                        if scene.hidden or effect is not None:
                            background=adaptive.render(frame,scene.background,now)
                            self.background_status=adaptive.status
                        else:
                            self.background_status='Fundo adaptativo aprendendo as áreas visíveis.'
                    else:
                        self.background_status='Fundo estático.' if scene.background is not None else ''
                    if effect is not None and background is not None:
                        output=effect.render(frame,background,now)
                        if effect.finished(now):
                            effect=None
                            gate.reset()
                            previous_observation=now
                            self._set_message('Desaparecido. Baixe a mão e repita para voltar.' if scene.hidden else 'Imagem ao vivo. Baixe a mão para armar o próximo gesto.')
                    else:
                        output=scene.render(frame)
                        if scene.hidden and background is not None: output=background.copy()
                except ValueError as error:
                    gate.reset()
                    effect=None
                    requested=None
                    self._set_message(str(error))
                    output=np.zeros_like(frame)
                self.hidden=scene.hidden
                self.phase=('calibrating' if calibration is not None else 'confirm' if scene.pending is not None else
                            'teleporting' if effect is not None or requested is not None else 'uncalibrated' if scene.background is None else
                            'hidden' if scene.hidden else 'holding' if gate.progress>0 else 'ready')
                if scene.background is not None and (self.effect_mode in EFFECTS or self.dynamic_background) and (effect is None or self.dynamic_background) and calibration is None and scene.pending is None:
                    self.need_silhouette.set()
                else: self.need_silhouette.clear()
                output_sent=False
                if virtual is not None:
                    try:
                        virtual.send(np.ascontiguousarray(output))
                        output_sent=True
                    except (RuntimeError,OSError,ValueError) as error:
                        virtual.close()
                        virtual=None
                        self.virtual_active=False
                        self.virtual_status=f'Falha da câmera virtual: {error}. Use Reconectar saída.'
                if scene.hidden and effect is None and requested is None:
                    if not announced_hidden:
                        self.disappearances.put((monotonic(),output_sent))
                        announced_hidden=True
                else:
                    announced_hidden=False
                count+=1
                if now-measured>=1:
                    self.fps=count/(now-measured)
                    measured,count=now,0
                with self.lock:
                    self.preview=scene.pending.copy() if scene.pending is not None else output
                    self.preview_revision+=1
                self.stop.wait(max(0,1/self.settings.fps-(monotonic()-tick)))
        except Exception as error:
            self.phase='error'
            self._set_message(str(error))
        finally:
            self.stop.set()
            if capture is not None: capture.release()
            if virtual is not None: virtual.close()
            if inference is not None: inference.join(timeout=2)
            if self.phase!='error': self.phase='stopped'
            self.virtual_active=False
            self.running=False
