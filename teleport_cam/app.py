from __future__ import annotations
from queue import Empty,Queue
from threading import Thread
from time import monotonic
import os
import subprocess
import webbrowser
import tkinter as tk
from PIL import Image, ImageTk
import customtkinter as ctk
import cv2
from .devices import CameraDevice,list_cameras
from .engine import Engine,Settings
from .hotkey import RestoreHotkey
from .preferences import load_preferences,save_preferences,apply_background_default
from .meet import MeetBridge,LeaveCountdown
from .theme import apply_theme,COLORS
from .effect_catalog import LABELS, DESCRIPTIONS
from .gesture_guides import guide_for, illustration_size
from .branding import set_process_identity, set_window_icon
from .paths import resource_root, extension_folder
from .platform_support import IS_MAC, UI_FONT, VIRTUAL_BACKENDS, CAMERA_PERMISSION_HINT, open_path

PHASES={
    'opening':'Abrindo câmera', 'uncalibrated':'Prepare o fundo', 'calibrating':'Capturando fundo',
    'confirm':'Confira o fundo vazio', 'ready':'Ao vivo', 'holding':'Preparando gesto',
    'teleporting':'Efeito em andamento', 'hidden':'Desaparecido', 'error':'Verifique a câmera', 'stopped':'Câmera parada',
}

def set_text(variable:tk.StringVar,value:str) -> None:
    if variable.get()!=value:
        variable.set(value)

class App:
    def __init__(self,root:tk.Tk) -> None:
        self.root=root
        self.engine:Engine | None=None
        self.image:ImageTk.PhotoImage | None=None
        self.preview_revision=-1
        self.controls_state:tuple[str,bool] | None=None
        self.wrap_width=-1
        self.last_progress=-1.0
        self.guide_image:ctk.CTkImage | None=None
        self.help_window:ctk.CTkToplevel | None=None
        self.devices:list[CameraDevice]=[]
        self.device_events:Queue[tuple[list[CameraDevice],str]]=Queue()
        self.scanning=False
        self.closing=False
        self.preferences=load_preferences()
        apply_background_default(self.preferences)
        self.bridge:MeetBridge | None=None
        self.bridge_error=''
        try: self.bridge=MeetBridge()
        except (OSError,ValueError) as error: self.bridge_error=f'Integração Meet indisponível: {error}'
        self.countdown=LeaveCountdown()
        self.bound_target=None
        self.leave_note=''
        self.leave_enabled=tk.BooleanVar(value=False)
        self.leave_delay=tk.StringVar(value='2')
        self.dynamic=tk.BooleanVar(value=self.preferences.get('background','static')=='live')
        self.hotkey=RestoreHotkey()
        self.settings_visible=False
        self.camera=tk.StringVar(value='Buscando sua câmera…')
        self.effect=tk.StringVar(value=self.preferences.get('effect','Teleporte anime'))
        if self.effect.get()=='Anime · teleporte': self.effect.set('Teleporte anime')
        if self.effect.get() not in LABELS: self.effect.set('Teleporte anime')
        self.resolution=tk.StringVar(value=self.preferences.get('resolution','1280 × 720'))
        if self.resolution.get() not in ('1280 × 720','640 × 480'): self.resolution.set('1280 × 720')
        self.hold=tk.StringVar(value=self.preferences.get('hold','1.0'))
        if self.hold.get() not in ('0.8','1.0','1.5','2.0'): self.hold.set('1.0')
        self.backend=tk.StringVar(value=self.preferences.get('backend','OBS Virtual Camera'))
        if self.backend.get() not in VIRTUAL_BACKENDS: self.backend.set('OBS Virtual Camera')
        root.title('Fora de Cena')
        set_window_icon(root)
        root.geometry('1080x790')
        root.minsize(860,700)
        apply_theme(root)
        root.columnconfigure(0,weight=1)
        root.rowconfigure(1,weight=1)
        font=(UI_FONT,13)
        c=COLORS
        header=ctk.CTkFrame(root,fg_color='transparent')
        header.grid(row=0,column=0,sticky='ew',padx=30,pady=(22,18))
        header.columnconfigure(1,weight=1)
        ctk.CTkLabel(header,text='Fora de Cena',font=(UI_FONT,23,'bold'),text_color=c['text']).grid(row=0,column=0,sticky='w')
        self.state_text=tk.StringVar(value='Câmera desligada')
        ctk.CTkLabel(header,textvariable=self.state_text,font=font,text_color=c['muted']).grid(row=0,column=1,sticky='e',padx=20)
        ctk.CTkButton(header,text='Configurar',command=self.toggle_settings,width=116,height=38,corner_radius=19,
            fg_color=c['panel'],hover_color='#e5e8ef',text_color=c['text'],font=font).grid(row=0,column=2)
        self.center=ctk.CTkFrame(root,fg_color='transparent')
        self.center.grid(row=1,column=0,sticky='nsew',padx=28)
        self.center.columnconfigure(0,weight=1)
        self.center.rowconfigure(0,weight=1)
        preview_frame=ctk.CTkFrame(self.center,fg_color=c['preview'],corner_radius=24)
        preview_frame.grid(row=0,column=0,sticky='nsew')
        preview_frame.columnconfigure(0,weight=1)
        preview_frame.rowconfigure(0,weight=1)
        self.preview=tk.Label(preview_frame,text='Sua câmera aparece aqui\n\nClique em Iniciar câmera para começar.',
            font=(UI_FONT,17),fg='#c8cfdd',bg=c['preview'],anchor='center',width=1,height=1,borderwidth=0)
        self.preview.grid(row=0,column=0,sticky='nsew',padx=14,pady=14)
        badge=ctk.CTkFrame(preview_frame,fg_color='#242b38',corner_radius=15)
        badge.place(x=18,y=18)
        ctk.CTkLabel(badge,textvariable=self.camera,font=(UI_FONT,12),text_color='#d6dce7').pack(padx=12,pady=3)
        self.step_text=tk.StringVar(value='Sua câmera só liga quando você clicar em Iniciar.')
        self.step_label=ctk.CTkLabel(self.center,textvariable=self.step_text,font=font,text_color=c['muted'],wraplength=850)
        self.step_label.grid(row=1,column=0,sticky='ew',pady=(12,2))
        self.hint=tk.StringVar(value='')
        guide_panel=ctk.CTkFrame(self.center,fg_color='transparent')
        guide_panel.grid(row=2,column=0,sticky='ew',pady=(6,2))
        guide_panel.columnconfigure(1,weight=1)
        self.guide_icon=ctk.CTkLabel(guide_panel,text='',width=64,height=64)
        self.guide_title=tk.StringVar()
        self.guide_instruction=tk.StringVar()
        ctk.CTkLabel(guide_panel,textvariable=self.guide_title,font=(UI_FONT,13,'bold'),text_color=c['text'],anchor='w').grid(row=0,column=1,sticky='w')
        self.guide_label=ctk.CTkLabel(guide_panel,textvariable=self.guide_instruction,font=(UI_FONT,12),text_color=c['muted'],anchor='w',justify='left',wraplength=680)
        self.guide_label.grid(row=1,column=1,sticky='ew')
        ctk.CTkButton(guide_panel,text='Como fazer',command=self.show_gesture_help,width=96,height=32,corner_radius=16,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=(UI_FONT,12)).grid(row=0,column=2,rowspan=2,sticky='e',padx=(14,0))
        self.hint_label=ctk.CTkLabel(self.center,textvariable=self.hint,font=(UI_FONT,12),text_color=c['muted'],height=18,wraplength=850)
        self.hint_label.grid(row=3,column=0,sticky='ew')
        self.progress=ctk.CTkProgressBar(self.center,height=3,corner_radius=2,fg_color=c['surface'],progress_color=c['accent'])
        self.progress.set(0)
        self.progress.grid(row=4,column=0,sticky='ew',padx=200,pady=(4,4))
        bar=ctk.CTkFrame(root,fg_color='transparent')
        bar.grid(row=2,column=0,sticky='ew',padx=30,pady=(10,12))
        bar.columnconfigure(1,weight=1)
        effects=ctk.CTkFrame(bar,fg_color='transparent')
        effects.grid(row=0,column=0,sticky='w')
        ctk.CTkLabel(effects,text='Efeito',font=(UI_FONT,12),text_color=c['muted']).pack(side='left',padx=(0,10))
        effect_combo=ctk.CTkComboBox(effects,variable=self.effect,values=list(LABELS),state='readonly',command=self.change_effect,
            width=205,height=36,corner_radius=12,border_width=0,fg_color=c['panel'],button_color=c['panel'],button_hover_color=c['surface'],text_color=c['text'],font=font)
        effect_combo.pack(side='left')
        modes=ctk.CTkFrame(bar,fg_color='transparent')
        modes.grid(row=0,column=2,sticky='e')
        ctk.CTkLabel(modes,text='Fundo',font=(UI_FONT,12),text_color=c['muted']).pack(side='left',padx=(0,10))
        self.background_mode=tk.StringVar(value='Em movimento' if self.dynamic.get() else 'Estático')
        self.background_selector=ctk.CTkSegmentedButton(modes,values=['Estático','Em movimento'],variable=self.background_mode,
            command=self.select_background,height=36,corner_radius=12,border_width=3,fg_color=c['surface'],unselected_color=c['surface'],
            unselected_hover_color='#dce1e9',selected_color='#dce0ff',selected_hover_color='#cdd3fa',text_color=c['text'],font=font)
        self.background_selector.pack(side='left')
        actions=ctk.CTkFrame(root,fg_color='transparent')
        actions.grid(row=3,column=0,sticky='ew',padx=30,pady=(0,8))
        actions.columnconfigure((0,2),weight=1)
        self.primary=ctk.CTkButton(actions,text='Iniciar câmera',command=self.primary_action,state='disabled',height=48,width=252,corner_radius=24,
            fg_color=c['accent'],hover_color=c['accent_hover'],text_color='#ffffff',font=(UI_FONT,15,'bold'))
        self.primary.grid(row=0,column=1)
        ctk.CTkButton(actions,text='Restaurar · F8',command=lambda:self.command('restore'),height=36,width=126,corner_radius=18,
            fg_color='transparent',hover_color=c['surface'],text_color=c['muted'],font=font).grid(row=0,column=2,sticky='e')
        self.main_meet_notice=tk.StringVar(value='')
        ctk.CTkLabel(root,textvariable=self.main_meet_notice,text_color=c['danger'],font=(UI_FONT,12),height=18).grid(row=4,column=0,sticky='ew')
        footer=ctk.CTkFrame(root,fg_color='transparent')
        footer.grid(row=5,column=0,sticky='ew',padx=30,pady=(0,12))
        footer.columnconfigure(0,weight=1)
        self.shortcut=tk.StringVar(value='Processamento local')
        ctk.CTkLabel(footer,textvariable=self.shortcut,font=(UI_FONT,11),text_color=c['muted']).grid(row=0,column=0,sticky='w')
        self.performance=tk.StringVar(value='Sem áudio')
        ctk.CTkLabel(footer,textvariable=self.performance,font=(UI_FONT,11),text_color=c['muted']).grid(row=0,column=1,sticky='e')
        self.settings_window=ctk.CTkFrame(root,width=410,height=570,corner_radius=22,fg_color=c['panel'],border_width=1,border_color=c['line'])
        self.settings_window.pack_propagate(False)
        panel_header=ctk.CTkFrame(self.settings_window,fg_color='transparent')
        panel_header.pack(fill='x',padx=22,pady=(16,0))
        ctk.CTkLabel(panel_header,text='Configurar',font=(UI_FONT,19,'bold'),text_color=c['text']).pack(side='left')
        ctk.CTkButton(panel_header,text='Fechar',width=64,height=30,corner_radius=15,fg_color=c['surface'],text_color=c['text'],hover_color=c['line'],command=self.toggle_settings).pack(side='right')
        self.tabs=ctk.CTkTabview(self.settings_window,corner_radius=16,fg_color=c['panel'],segmented_button_selected_color=c['accent'],segmented_button_selected_hover_color=c['accent_hover'])
        self.tabs.pack(fill='both',expand=True,padx=12,pady=(0,12))
        camera_tab=self.tabs.add('Câmera')
        meet_tab=self.tabs.add('Meet')
        self.config=ctk.CTkScrollableFrame(camera_tab,fg_color='transparent')
        self.config.pack(fill='both',expand=True)
        self.config.columnconfigure(0,weight=1)
        def label(parent:ctk.CTkFrame,text:str,row:int) -> None:
            ctk.CTkLabel(parent,text=text,text_color=c['muted'],font=font,anchor='w').grid(row=row,column=0,sticky='w',pady=(12,5))
        def combo(parent:ctk.CTkFrame,variable:tk.StringVar,values:list[str],row:int) -> ctk.CTkComboBox:
            widget=ctk.CTkComboBox(parent,variable=variable,values=values,state='readonly',height=38,corner_radius=10,
                border_color=c['line'],fg_color='#ffffff',button_color=c['surface'],button_hover_color=c['line'],text_color=c['text'],font=font)
            widget.grid(row=row,column=0,sticky='ew')
            return widget
        label(self.config,'Webcam',0)
        self.camera_combo=combo(self.config,self.camera,[],1)
        self.camera_combo.configure(state='disabled')
        self.refresh_button=ctk.CTkButton(self.config,text='Atualizar lista',command=self.refresh_devices,height=32,corner_radius=10,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font)
        self.refresh_button.grid(row=2,column=0,sticky='w',pady=(8,0))
        self.start_button=ctk.CTkButton(self.config,text='Iniciar câmera',command=self.start,state='disabled',height=36,corner_radius=10,
            fg_color=c['accent'],hover_color=c['accent_hover'],font=font)
        self.start_button.grid(row=3,column=0,sticky='ew',pady=(10,0))
        label(self.config,'Qualidade',4)
        resolution_combo=combo(self.config,self.resolution,['1280 × 720','640 × 480'],5)
        label(self.config,'Duração das poses (estalo e pinça usam movimento)',6)
        hold_combo=combo(self.config,self.hold,['0.8','1.0','1.5','2.0'],7)
        self.recalibrate=ctk.CTkButton(self.config,text='Capturar fundo novamente',command=lambda:self.command('calibrate'),state='disabled',
            height=36,corner_radius=10,fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font)
        self.recalibrate.grid(row=8,column=0,sticky='ew',pady=(18,8))
        self.background_description=tk.StringVar()
        ctk.CTkLabel(self.config,textvariable=self.background_description,wraplength=315,text_color=c['muted'],font=(UI_FONT,12),justify='left').grid(row=9,column=0,sticky='w')
        self.status=tk.StringVar(value='Nenhuma imagem está sendo capturada.')
        self.status_label=ctk.CTkLabel(self.config,textvariable=self.status,wraplength=315,justify='left',text_color=c['muted'],font=(UI_FONT,12))
        self.status_label.grid(row=10,column=0,sticky='ew',pady=(14,0))
        self.right=ctk.CTkScrollableFrame(meet_tab,fg_color='transparent')
        self.right.pack(fill='both',expand=True)
        self.right.columnconfigure(0,weight=1)
        label(self.right,'Câmera enviada à chamada',0)
        backend_combo=combo(self.right,self.backend,list(VIRTUAL_BACKENDS),1)
        self.output_help=tk.StringVar(value='No Meet, escolha OBS Virtual Camera. Se ainda não instalou o OBS, clique em Preparar vídeo para o Meet.')
        ctk.CTkLabel(self.right,textvariable=self.output_help,wraplength=315,
            text_color=c['muted'],font=font,justify='left').grid(row=2,column=0,sticky='w',pady=10)
        ctk.CTkButton(self.right,text='Preparar vídeo para o Meet',command=self.prepare_meet,height=36,corner_radius=10,
            fg_color=c['accent'],hover_color=c['accent_hover'],font=font).grid(row=3,column=0,sticky='ew')
        ctk.CTkButton(self.right,text='Reconectar saída',command=lambda:self.command('virtual'),height=32,corner_radius=10,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font).grid(row=4,column=0,sticky='w',pady=(8,14))
        self.leave_toggle=ctk.CTkSwitch(self.right,text='Sair do Meet após desaparecer',variable=self.leave_enabled,command=self.toggle_leave,
            progress_color=c['accent'],text_color=c['text'],font=font)
        self.leave_toggle.grid(row=5,column=0,sticky='w',pady=(8,8))
        ctk.CTkLabel(self.right,text='Opcional. Requer a extensão e fecha apenas a aba vinculada.',text_color=c['muted'],font=(UI_FONT,12),wraplength=315).grid(row=6,column=0,sticky='w')
        label(self.right,'Esperar antes de sair (segundos)',7)
        combo(self.right,self.leave_delay,['2','3','5'],8)
        ctk.CTkButton(self.right,text='Conectar extensão · instruções',command=self.show_meet_help,height=34,corner_radius=10,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font).grid(row=9,column=0,sticky='ew',pady=(14,8))
        ctk.CTkButton(self.right,text='Abrir pasta da extensão',command=self.open_extension,height=34,corner_radius=10,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font).grid(row=10,column=0,sticky='ew')
        ctk.CTkButton(self.right,text='Copiar código de conexão',command=self.copy_meet_code,height=34,corner_radius=10,
            fg_color=c['surface'],hover_color=c['line'],text_color=c['text'],font=font).grid(row=11,column=0,sticky='ew',pady=(8,0))
        self.meet_status=tk.StringVar(value=self.bridge_error or 'Extensão não vinculada. O vídeo funciona sem ela.')
        self.meet_label=ctk.CTkLabel(self.right,textvariable=self.meet_status,wraplength=315,text_color=c['muted'],font=(UI_FONT,12),justify='left')
        self.meet_label.grid(row=12,column=0,sticky='ew',pady=(12,0))
        self.inputs=[self.camera_combo,resolution_combo,backend_combo,hold_combo]
        self.update_background_description()
        self.update_gesture_guide()
        self.hold.trace_add('write',lambda *_args:self.update_gesture_guide())
        root.bind('<F8>',lambda _event:self.command('restore'))
        root.bind('<Escape>',lambda _event:self.hide_settings())
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh_devices()
        self.poll()

    def hide_settings(self) -> None:
        self.settings_visible=False
        self.settings_window.place_forget()

    def change_effect(self,value:str) -> None:
        mode=LABELS[value]
        self.hint.set(DESCRIPTIONS[mode])
        self.update_gesture_guide()
        if self.engine is not None and self.engine.running:
            self.engine.commands.put('effect:'+mode)
        self.preferences['effect']=value
        try: save_preferences(self.preferences)
        except OSError: self.status.set('Não consegui salvar o efeito; ele continua válido nesta sessão.')

    def update_gesture_guide(self) -> None:
        guide=guide_for(LABELS[self.effect.get()])
        self.guide_title.set(guide.title)
        instruction=guide.instruction
        if not guide.motion and guide.kind!='manual': instruction+=f' Segure por {self.hold.get()} s.'
        self.guide_instruction.set(instruction)
        self.guide_icon.grid_remove()
        self.guide_image=None
        path=resource_root()/'assets'/'gestures'/guide.image
        if path.is_file():
            try:
                with Image.open(path) as source:
                    if max(source.size)>2048: raise ValueError('Ilustração grande demais.')
                    image=source.convert('RGBA')
                    image.thumbnail((512,512))
                self.guide_image=ctk.CTkImage(light_image=image,dark_image=image,size=illustration_size(image.size,64))
                self.guide_icon.configure(image=self.guide_image)
                self.guide_icon.grid(row=0,column=0,rowspan=2,padx=(0,12))
            except (OSError,ValueError,Image.DecompressionBombError):
                self.guide_image=None
        if self.help_window is not None and self.help_window.winfo_exists(): self.help_window.destroy()

    def show_gesture_help(self) -> None:
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.lift()
            return
        guide=guide_for(LABELS[self.effect.get()])
        window=ctk.CTkToplevel(self.root)
        self.help_window=window
        window.title(guide.title+' · Fora de Cena')
        set_window_icon(window)
        window.geometry('520x550')
        window.minsize(480,460)
        window.transient(self.root)
        window.configure(fg_color=COLORS['shell'])
        window.bind('<F8>',lambda _event:self.command('restore'))
        window.bind('<Escape>',lambda _event:window.destroy())
        content=ctk.CTkScrollableFrame(window,fg_color='transparent')
        content.pack(fill='both',expand=True,padx=22,pady=18)
        ctk.CTkLabel(content,text=guide.title,font=(UI_FONT,21,'bold'),text_color=COLORS['text']).pack(anchor='w',pady=(0,16))
        if self.guide_image is not None:
            source=self.guide_image.cget('light_image')
            large=ctk.CTkImage(light_image=source,dark_image=source,size=illustration_size(source.size,280))
            label=ctk.CTkLabel(content,text='',image=large)
            label.pack(pady=(0,14))
        for index,step in enumerate(guide.steps,1):
            ctk.CTkLabel(content,text=f'{index}. {step}',font=(UI_FONT,14),text_color=COLORS['text'],wraplength=410,justify='left',anchor='w').pack(fill='x',pady=(0,12))
        ctk.CTkLabel(content,text='A ativação alterna sair e voltar. O botão continua disponível; Restaurar ou F8 interrompe o efeito.',font=(UI_FONT,12),text_color=COLORS['muted'],wraplength=410,justify='left').pack(anchor='w',pady=(4,12))

    def select_background(self,value:str) -> None:
        self.dynamic.set(value=='Em movimento')
        self.change_background()

    def update_background_description(self) -> None:
        self.background_description.set('Áreas visíveis ao vivo. O espaço atrás de você usa o fundo aprendido.' if self.dynamic.get() else 'Usa a captura vazia inteira. Mais leve e previsível.')

    def change_background(self) -> None:
        self.update_background_description()
        if self.engine is not None and self.engine.running:
            self.engine.commands.put('background:live' if self.dynamic.get() else 'background:static')
        self.preferences['background']='live' if self.dynamic.get() else 'static'
        try: save_preferences(self.preferences)
        except OSError: self.status.set('Não consegui salvar a preferência; a troca continua válida nesta sessão.')

    def toggle_meet(self) -> None:
        self.toggle_settings()
        self.tabs.set('Meet')

    def show_meet_help(self) -> None:
        help_window=ctk.CTkToplevel(self.root)
        help_window.title('Conectar a extensão')
        set_window_icon(help_window)
        help_window.geometry('580x430')
        help_window.transient(self.root)
        text=('A extensão só serve para sair automaticamente.\n\n'
              '1. No Chrome/Edge, abra Extensões, ative Modo do desenvolvedor e carregue a pasta meet_extension sem compactação.\n\n'
              '2. Copie o código de conexão no aplicativo. Na aba da reunião, abra a extensão e clique Vincular.\n\n'
              '3. Ative Sair do Meet após desaparecer. F8 cancela durante a contagem.')
        ctk.CTkLabel(help_window,text=text,wraplength=510,justify='left',font=(UI_FONT,14),text_color=COLORS['text']).pack(padx=26,pady=26,anchor='w')
        ctk.CTkButton(help_window,text='Abrir guia completo',command=lambda:open_path(resource_root()/'GUIA_RAPIDO.html'),
            fg_color=COLORS['accent'],hover_color=COLORS['accent_hover'],corner_radius=12).pack(padx=26,anchor='w')

    def prepare_meet(self) -> None:
        if self.engine is not None and self.engine.running:
            self.status.set('Pare a câmera antes de preparar a saída para o Meet.')
            return
        if self.scanning:
            self.status.set('Aguarde a busca de câmeras terminar e tente novamente.')
            return
        if not any('obs' in device.name.lower() and 'virtual' in device.name.lower() for device in self.devices):
            if IS_MAC:
                self.output_help.set('Não encontrei OBS Virtual Camera. Instale o OBS pelo site oficial, abra-o uma vez, clique em '
                    'Iniciar câmera virtual e aprove a extensão de câmera em Ajustes do Sistema; depois pare a câmera virtual no OBS '
                    'e clique em Atualizar lista na aba Câmera.')
            else:
                self.output_help.set('Não encontrei OBS Virtual Camera. Instale o OBS pelo site oficial; depois clique em Atualizar lista na aba Câmera. Não é preciso manter o OBS aberto.')
            self.status.set('Abrindo o download oficial do OBS. A instalação é feita por você; o app não instala drivers automaticamente.')
            webbrowser.open('https://obsproject.com/download')
            return
        self.backend.set('OBS Virtual Camera')
        self.status.set('Pronto para iniciar. No Meet, escolha OBS Virtual Camera e desative desfoque/fundo virtual. Deixe a câmera virtual parada no OBS.')

    def copy_meet_code(self) -> None:
        if self.bridge is None:
            self.meet_status.set(self.bridge_error)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.bridge.token)
        self.leave_note='Código copiado. Cole na extensão aberta na aba do Meet e clique Vincular.'

    def open_extension(self) -> None:
        try:
            open_path(extension_folder())
        except (OSError,subprocess.SubprocessError):
            self.leave_note='Não consegui preparar a pasta da extensão. Confira o acesso à sua pasta de dados e tente novamente.'

    def toggle_leave(self) -> None:
        if self.leave_enabled.get() and (self.bridge is None or not self.bridge.connected()):
            self.leave_enabled.set(False)
            self.leave_note='Vincule uma aba do Meet pela extensão antes de ativar a saída automática.'
        else:
            self.leave_note='Saída automática ativada somente para a aba vinculada.' if self.leave_enabled.get() else 'Saída automática desligada.'
        self.countdown.enabled=self.leave_enabled.get()
        self.countdown.cancel()
        if self.bridge is not None: self.bridge.cancel()

    def poll_meet(self) -> None:
        if self.bridge is None:
            self.leave_toggle.configure(state='disabled')
            self.meet_status.set(self.bridge_error)
            return
        if self.bridge.target!=self.bound_target:
            self.bound_target=self.bridge.target
            self.leave_enabled.set(False)
            self.countdown.enabled=False
            self.countdown.cancel()
            self.leave_note=''
        connected=self.bridge.connected()
        engine=self.engine
        ready=connected and engine is not None and engine.running and engine.virtual_active
        if engine is not None:
            while True:
                try: when,sent=engine.disappearances.get_nowait()
                except Empty: break
                if self.leave_enabled.get():
                    self.countdown.enabled=True
                    self.countdown.delay=float(self.leave_delay.get())
                    armed=self.countdown.arm(monotonic(),ready and sent and monotonic()-when<1)
                    self.leave_note='' if armed else 'Não saí do Meet: vincule a extensão e mantenha a câmera virtual ativa.'
        hidden=engine is not None and engine.hidden and engine.phase=='hidden'
        if self.countdown.due(monotonic(),hidden,ready):
            requested=self.bridge.request_leave(self.bound_target)
            self.leave_enabled.set(False)
            self.leave_note='' if requested else 'Não saí do Meet: a extensão não está conectada.'
        if self.countdown.deadline is not None:
            remaining=max(0,self.countdown.deadline-monotonic())
            set_text(self.meet_status,f'Saindo do Meet em {remaining:.1f} s. F8 ou desativar o toggle cancela.')
        else:
            set_text(self.meet_status,self.leave_note or self.bridge.status)
        output_missing=engine is not None and engine.running and engine.settings.virtual!='off' and not engine.virtual_active
        notice=(self.meet_status.get() if self.countdown.deadline is not None else
                'Saída automática do Meet ativada' if self.leave_enabled.get() else
                'Saída virtual indisponível · abra Configurar → Meet' if output_missing else '')
        set_text(self.main_meet_notice,notice)

    def toggle_settings(self) -> None:
        if self.settings_visible:
            self.hide_settings()
            return
        self.settings_visible=True
        self.settings_window.configure(height=max(400,min(570,self.root.winfo_height()-96)))
        self.settings_window.place(relx=1,x=-25,y=76,anchor='ne')
        self.settings_window.lift()
        self.settings_window.focus_set()

    def refresh_devices(self) -> None:
        if self.scanning or (self.engine is not None and self.engine.running): return
        self.scanning=True
        self.refresh_button.configure(state='disabled')
        self.start_button.configure(state='disabled')
        def scan() -> None:
            try: self.device_events.put((list_cameras(),''))
            except Exception as error: self.device_events.put(([],str(error)))
        Thread(target=scan,daemon=True,name='camera-list').start()

    def accept_devices(self) -> None:
        try: devices,error=self.device_events.get_nowait()
        except Empty: return
        self.devices=devices
        self.scanning=False
        self.refresh_button.configure(state='normal')
        self.camera_combo.configure(values=[d.label for d in devices],state='readonly' if devices else 'disabled')
        if devices:
            current=next((d for d in devices if d.label==self.camera.get()),None)
            preferred=next((d for d in devices if d.path and d.path==self.preferences.get('camera_path')),None)
            selected=current or preferred or next((d for d in devices if not d.virtual),devices[0])
            self.camera.set(selected.label)
            self.start_button.configure(state='normal')
            if self.engine is None or not self.engine.running: self.primary.configure(text='Iniciar câmera',state='normal')
        else:
            self.camera.set('Nenhuma webcam encontrada')
            self.status.set(f'Não encontrei webcams. Conecte a câmera e clique Atualizar. {error}')
            self.step_text.set('Conecte sua webcam. Em Configurar → Câmera, clique em Atualizar lista.')
            self.hint.set(error or CAMERA_PERMISSION_HINT)

    def start(self) -> None:
        if self.engine is not None and self.engine.thread.is_alive():
            self.stop()
            return
        device=next((d for d in self.devices if d.label==self.camera.get()),None)
        if device is None:
            self.status.set('Selecione uma webcam disponível.')
            return
        width,height=(int(v.strip()) for v in self.resolution.get().split('×'))
        backend=VIRTUAL_BACKENDS[self.backend.get()]
        self.engine=Engine(Settings(camera=device.index,camera_backend=device.backend,width=width,height=height,
            hold=float(self.hold.get()),virtual=backend,effect=LABELS[self.effect.get()],dynamic_background=self.dynamic.get()))
        self.preview_revision=-1
        self.preferences={'camera_path':device.path,'resolution':self.resolution.get(),'backend':self.backend.get(),
                          'hold':self.hold.get(),'effect':self.effect.get(),'background':'live' if self.dynamic.get() else 'static'}
        try: save_preferences(self.preferences)
        except OSError: self.engine._set_message('Não consegui salvar as preferências. A sessão continua normalmente.')
        for entry in self.inputs: entry.configure(state='disabled')
        self.refresh_button.configure(state='disabled')
        self.start_button.configure(text='Parar câmera',state='normal')

    def primary_action(self) -> None:
        if self.engine is None or not self.engine.running:
            self.start()
            return
        phase=self.engine.phase
        self.command('confirm' if phase=='confirm' else 'calibrate' if phase=='uncalibrated' else 'toggle')

    def command(self,name:str) -> None:
        if name in ('restore','calibrate') or (name=='toggle' and self.engine is not None and self.engine.hidden):
            self.countdown.cancel()
            if self.bridge is not None: self.bridge.cancel()
            self.leave_note='Saída automática cancelada.'
        if self.engine is not None and self.engine.running: self.engine.commands.put(name)

    def stop(self) -> None:
        self.countdown.cancel()
        if self.bridge is not None: self.bridge.cancel()
        if self.engine is not None:
            self.engine.stop.set()
            self.start_button.configure(state='disabled',text='Parando…')

    def poll(self) -> None:
        if self.closing: return
        self.accept_devices()
        if self.hotkey.requested.is_set():
            self.hotkey.requested.clear()
            self.command('restore')
        if self.hotkey.ready.is_set():
            if self.hotkey.registered: shortcut='Tudo local · F8 restaura mesmo fora desta janela'
            elif IS_MAC: shortcut='Tudo local · F8 (ou fn + F8) restaura com esta janela em foco'
            else: shortcut='F8 só nesta janela · atalho global ocupado'
            set_text(self.shortcut,shortcut)
        if self.engine is not None:
            frame,status,fps=self.engine.snapshot()
            phase=self.engine.phase
            running=self.engine.running
            set_text(self.state_text,PHASES.get(phase,phase))
            set_text(self.status,status)
            set_text(self.performance,f'{fps:.1f} FPS · {self.effect.get()}')
            if self.last_progress!=self.engine.progress:
                self.last_progress=self.engine.progress
                self.progress.set(self.engine.progress)
            set_text(self.hint,self.engine.vision_hint if phase in ('ready','holding','hidden') else '')
            steps={
                'uncalibrated':'Capture o cenário vazio antes de usar o efeito.',
                'calibrating':'Saia do enquadramento e aguarde a captura.',
                'confirm':'A prévia mostra o fundo capturado. Confirme somente se estiver vazio.',
                'hidden':'Você desapareceu. Repita o gesto ou clique Reaparecer.',
                'ready':'Faça o gesto indicado abaixo ou use Ativar efeito.',
                'holding':'Mantenha a posição até completar a barra.',
                'teleporting':'Efeito em andamento. F8 cancela e restaura.',
            }
            set_text(self.step_text,status.split('\n')[0] if phase=='error' else steps.get(phase,'Inicie a câmera para continuar.'))
            if self.engine.effect_error and phase in ('ready','hidden'):
                set_text(self.hint,self.engine.effect_error)
            elif self.engine.gesture_error and phase in ('ready','hidden'):
                set_text(self.hint,self.engine.gesture_error)
            elif self.engine.gesture_release_required and phase in ('ready','hidden'):
                set_text(self.hint,'Baixe ou relaxe a mão por um instante; depois faça o gesto para iniciar a barra.')
            elif phase in ('ready','hidden') and self.engine.message.startswith(('Não ','Falha','Recorte','Modelo')):
                set_text(self.hint,self.engine.message)
            label=('Capturar fundo (4 s)' if phase=='uncalibrated' else 'Confirmar fundo vazio' if phase=='confirm' else 'Reaparecer' if self.engine.hidden else 'Ativar efeito')
            changed=self.controls_state!=(phase,running)
            if changed:
                self.controls_state=(phase,running)
                self.primary.configure(text=label,state='normal' if running and phase in ('uncalibrated','confirm','ready','holding','hidden') else 'disabled')
                self.recalibrate.configure(state='normal' if running and phase in ('confirm','ready','holding','hidden') else 'disabled')
            if frame is not None and self.preview_revision!=self.engine.preview_revision:
                self.preview_revision=self.engine.preview_revision
                height,width=frame.shape[:2]
                scale=min(max(100,self.preview.winfo_width()-4)/width,max(100,self.preview.winfo_height()-4)/height)
                small=cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale))),interpolation=cv2.INTER_AREA)
                image=Image.fromarray(cv2.cvtColor(cv2.flip(small,1),cv2.COLOR_BGR2RGB))
                self.image=ImageTk.PhotoImage(image)
                self.preview.configure(image=self.image,text='')
            if not running and changed:
                for entry in self.inputs: entry.configure(state='readonly')
                self.camera_combo.configure(state='readonly' if self.devices else 'disabled')
                self.refresh_button.configure(state='normal')
                self.start_button.configure(text='Iniciar câmera',state='normal' if self.devices else 'disabled')
                self.primary.configure(text='Iniciar câmera',state='normal' if self.devices else 'disabled')
        self.poll_meet()
        available=max(270,self.center.winfo_width()-32)
        if self.wrap_width!=available:
            self.wrap_width=available
            self.hint_label.configure(wraplength=available)
            self.step_label.configure(wraplength=available)
            self.guide_label.configure(wraplength=max(350,available-190))
        self.root.after(33,self.poll)

    def close(self) -> None:
        self.closing=True
        self.stop()
        self.hotkey.close()
        if self.bridge is not None: self.bridge.close()
        self._finish_close()

    def _finish_close(self) -> None:
        if self.engine is not None and self.engine.thread.is_alive(): self.root.after(100,self._finish_close)
        else: self.root.destroy()

def main() -> None:
    set_process_identity()
    root=ctk.CTk()
    App(root)
    root.mainloop()
