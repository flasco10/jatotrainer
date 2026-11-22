"""Small text-baseline adjustment shared by jatotrainer's interfaces."""
import tkinter as tk
import customtkinter as ctk


def install_text_alignment():
    if getattr(ctk,'_jatotrainer_alignment',False):return
    ctk._jatotrainer_alignment=True
    for cls,attr in [(ctk.CTkButton,'_text_label'),(ctk.CTkLabel,'_label'),(ctk.CTkOptionMenu,'_text_label'),(ctk.CTkEntry,'_entry')]:
        original=cls._create_grid
        def create_grid(self,_original=original,_attr=attr):
            _original(self)
            label=getattr(self,_attr,None)
            if label is not None:
                offset=round(self._apply_widget_scaling(4))
                if _attr=='_entry':
                    label.grid_configure(pady=(self._apply_widget_scaling(self._border_width)+offset,self._apply_widget_scaling(self._border_width+1)))
                else:label.grid_configure(pady=(offset,0))
        cls._create_grid=create_grid
    for cls in (ctk.CTkSwitch,ctk.CTkCheckBox):
        original=cls._draw
        def draw(self,*args,_original=original,**kwargs):
            _original(self,*args,**kwargs)
            label=getattr(self,'_text_label',None)
            if label is not None:label.grid_configure(pady=(round(self._apply_widget_scaling(4)),0))
        cls._draw=draw


class TextCanvas(tk.Canvas):
    def create_text(self,*args,**kwargs):
        if len(args)==1:
            x,y=args[0];args=(x,y+2)
        elif len(args)>=2:args=(args[0],args[1]+2,*args[2:])
        return super().create_text(*args,**kwargs)


def chart_backdrop(background, width, height):
    """Draw the rounded, tinted background shared by chart cards."""
    from PIL import Image, ImageDraw, ImageOps

    image = Image.new("RGB", (width, height), "#171d30")
    if background is not None:
        image = ImageOps.fit(background, (width, height), method=Image.Resampling.LANCZOS)
        image = Image.blend(image, Image.new("RGB", (width, height), "#111322"), .58)
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rounded_rectangle((1, 1, width-2, height-2), radius=24, fill=255)
    image.putalpha(mask)
    ImageDraw.Draw(image).rounded_rectangle((2, 2, width-3, height-3), radius=24, outline="#9c95aa", width=3)
    return image
