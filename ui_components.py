"""Small text-baseline adjustment shared by jatotrainer's interfaces."""
from functools import lru_cache
import tkinter as tk
from PIL import Image, ImageDraw, ImageOps, ImageTk
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


@lru_cache(maxsize=96)
def _rounded_mask(width, height, radius, inset=0):
    """Rasterize the outline at 4× and reduce it to clean subpixel edges."""
    scale = 4
    mask = Image.new("L", (width * scale, height * scale))
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset * scale, inset * scale, (width - inset) * scale - 1,
         (height - inset) * scale - 1),
        radius=max(0, radius - inset) * scale, fill=255,
    )
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def chart_backdrop(background, width, height, *, radius=24, fill="#171d30",
                   tint="#111322", shade=.58, outline="#7382a0"):
    """Draw the rounded, tinted background shared by chart cards."""
    size = (width, height)
    image = Image.new("RGB", size, fill)
    if background is not None:
        image = ImageOps.fit(background, size, method=Image.Resampling.LANCZOS)
        image = Image.blend(image, Image.new("RGB", size, tint), shade)
    border = Image.new("RGB", size, outline)
    border.paste(image, (0, 0), _rounded_mask(width, height, radius, 1))
    border.putalpha(_rounded_mask(width, height, radius))
    return border


@lru_cache(maxsize=128)
def _pill_image(width, height, fill, outline):
    radius = min(width, height) // 2
    image = Image.new("RGB", (width, height), outline)
    image.paste(fill, (0, 0, width, height), _rounded_mask(width, height, radius, 1))
    image.putalpha(_rounded_mask(width, height, radius))
    return image


def draw_chart_pill(canvas, images, x, y, width, height, text, font, fill, outline, color="white"):
    """Draw a true capsule with antialiased edges and native-resolution text."""
    photo = ImageTk.PhotoImage(_pill_image(width, height, fill, outline), master=canvas)
    images.append(photo)
    canvas.create_image(x, y, image=photo, anchor="nw")
    canvas.create_text(x + width / 2, y + height / 2, text=text, fill=color, font=font)
