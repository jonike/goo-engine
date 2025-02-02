# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

"""
Light group key management.
"""

import bpy
from bpy.types import Panel,  Material, Light, PropertyGroup, UIList, UI_UL_list, Operator
from bpy.props import StringProperty, CollectionProperty, IntProperty, PointerProperty, EnumProperty, BoolProperty
from bpy.utils import register_classes_factory
from bpy.app.handlers import persistent
# from time import perf_counter

SIZEOF_INT = 32
MAX_LIGHT_GROUP_BIT = 127


def set_bit(vec, bit):
    index = bit // SIZEOF_INT
    mask = 1 << ((bit + 1) % SIZEOF_INT)
    if index > 3:
        return
    vec[index] |= mask


def map_bits(data, mapping):
    data.light_group_bits = (0, 0, 0, 0)
    is_mat = isinstance(data, Material)
    if is_mat:
        data.light_group_shadow_bits = data.light_group_bits

    for grp in data.light_groups.groups:
        index = mapping.get(grp.name)
        if index is not None:
            set_bit(data.light_group_bits, index)
            if is_mat and not grp.ignore_shadow:
                set_bit(data.light_group_shadow_bits, index)

    if data.light_groups.use_default:
        set_bit(data.light_group_bits, MAX_LIGHT_GROUP_BIT)
        if is_mat and not data.light_groups.ignore_default_shadow:
            set_bit(data.light_group_shadow_bits, MAX_LIGHT_GROUP_BIT)


def sync_light_groups():
    # Populate light bit set with groups from Light objects, merging duplicates
    light_names = set()

    for light in bpy.data.lights:
        for grp in light.light_groups.groups:
            light_names.add(grp.name)

    if len(light_names) >= MAX_LIGHT_GROUP_BIT:
        print("WARNING: Max number of light groups (127) reached. Some Light Groups will not be included.")

    # Assign bit numbers - default group is reserved at 127
    bit_mapping = {name: index for index, name in enumerate(light_names)}

    # Assign bits to each material/light through lookup
    for mat in bpy.data.materials:
        map_bits(mat, bit_mapping)

    for light in bpy.data.lights:
        map_bits(light, bit_mapping)


def update_handler(_s, _c):
    sync_light_groups()


@persistent
def sync_handler(*_):
    sync_light_groups()

@persistent
def sync_dg_handler(scn, dg):
    if dg.mode == 'RENDER':
        return

    for update in dg.updates:
        uid = update.id

        if not uid:
            continue

        if isinstance(uid, bpy.types.Material) or isinstance(uid, bpy.types.Light):
            sync_light_groups()
            return


def rename_group(data, src, tgt):
    if data.library:
        return
    for grp in data.light_groups.groups:
        if grp.name == src:
            grp.name = tgt


def get_name(self):
    return self.name


# Update all matching names in the entire file
def set_name(self, value):
    orig_name = self.name
    for mat in bpy.data.materials:
        rename_group(mat, orig_name, value)
    for light in bpy.data.lights:
        rename_group(light, orig_name, value)


class LightGroup(PropertyGroup):
    name: StringProperty()
    viz_name: StringProperty(name="Name", get=get_name, set=set_name)
    ignore_shadow: BoolProperty(name="Ignore Shadows", description="Ignore shadows cast from this light group", default=False, options=set())


class LightGroups(PropertyGroup):
    groups: CollectionProperty(type=LightGroup)
    group_index: IntProperty(name="Active Light Group", update=update_handler)
    use_default: BoolProperty(name="Use default Light Group", default=True, description="Use builtin default light group", update=update_handler)
    ignore_default_shadow: BoolProperty(name="Ignore default Light Group shadows", default=False, description="Ignore default light group shadows", update=update_handler)


def get_name_set():
    names = set()
    for mat in bpy.data.materials:
        for grp in mat.light_groups.groups:
            names.add(grp.name)

    for light in bpy.data.lights:
        for grp in light.light_groups.groups:
            names.add(grp.name)

    return names


def unique_group_name():
    names = get_name_set()
    i = 1
    name = "LightGroup"
    while name in names:
        name = f"LightGroup.{i:03}"
        i += 1
    return name


class MAT_UL_LightGroupList(UIList):
    def draw_item(self,
                  context: 'Context',
                  layout: 'UILayout',
                  data: 'AnyType',
                  item: 'AnyType',
                  icon: int,
                  active_data: 'AnyType',
                  active_property: str,
                  index: int = 0,
                  flt_flag: int = 0):
        row = layout.row(align=True)
        row.prop(item, "viz_name", emboss=False, text="")
        if isinstance(data.id_data, Material):
            row.prop(item, "ignore_shadow", text="", icon="REC" if item.ignore_shadow else "OVERLAY", emboss=False)

    def filter_items(self, context: 'Context', data: 'AnyType', property: str):
        keys = getattr(data, property)
        flt_flags = []
        flt_order = []

        helper_funcs = UI_UL_list

        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(self.filter_name, self.bitflag_filter_item, keys, "name")

        if self.use_filter_sort_alpha:
            flt_order = helper_funcs.sort_items_by_name(keys, "name")

        return flt_flags, flt_order


def get_groups(obj):
    if obj.type == 'LIGHT':
        return obj.data.light_groups
    mat = obj.active_material
    if not mat:
        mat = obj.material_slots[0].material
    return mat.light_groups


class ALightGroupPanel(Panel):
    bl_label = "Light Groups"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'

    def get_groups(self, ctx):
        obj = ctx.object
        return get_groups(obj)

    def draw_header(self, context):
        ...

    def draw(self, ctx: 'bpy.types.Context'):
        layout = self.layout
        groups = self.get_groups(ctx)
        row = layout.row()
        row.template_list("MAT_UL_LightGroupList", "",
                          groups, "groups", groups, "group_index",
                          rows=5, type='DEFAULT')
        # Right hand column with operators
        col = row.column(align=True)
        col.operator('light_groups.link', icon='LINKED', text="")
        col.operator('light_groups.unlink', icon='UNLINKED', text="")
        col.separator()
        col.operator('light_groups.new', icon='ADD', text="")
        col.operator('light_groups.remove', icon='REMOVE', text="")
        col.separator()
        col.operator('light_groups.resync', icon='FILE_REFRESH', text="")

        # Below Operators
        row = layout.row()
        row.prop(groups, 'use_default', text="Use Default Group")
        if self.bl_context != "data":
            row = row.row()
            row.enabled = groups.use_default
            row.prop(groups, 'ignore_default_shadow', text="Ignore Default Shadows")


class OBJ_PT_MLightGroupPanel(ALightGroupPanel):
    bl_context = 'material'

    def get_groups(self, ctx):
        mat = ctx.material
        ob = ctx.object

        if ob:
            data = ob.active_material
        elif mat:
            data = mat
        return data.light_groups

    @classmethod
    def poll(cls, ctx):
        return ctx.material

class OBJ_PT_LLightGroupPanel(ALightGroupPanel):
    bl_context = 'data'

    def get_groups(self, ctx):
        ob = ctx.object
        light = ctx.light
        space = ctx.space_data

        if ob:
            data = ob.data
        elif light:
            data = space.pin_id

        return data.light_groups

    @classmethod
    def poll(cls, ctx):
        return ctx.light


class LightGroupOp(Operator):
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, ctx):
        try:
            get_groups(ctx.object)
            return True
        except Exception as e:
            return False


class LightGroupSelectionOp(Operator):
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, ctx):
        try:
            grp = get_groups(ctx.object)
            return 0 <= grp.group_index < len(grp.groups)
        except Exception as e:
            return False


class MAT_OT_NewLightGroup(LightGroupOp):
    """ Create a new unique light group """
    bl_label = "New Light Group"
    bl_idname = 'light_groups.new'

    def execute(self, ctx):
        lgs = get_groups(ctx.object)
        name = unique_group_name()
        new = lgs.groups.add()
        new.name = name

        lgs.group_index = lgs.groups.find(new.name)

        sync_light_groups()
        return {'FINISHED'}


class MAT_OT_LinkLightGroup(LightGroupOp):
    """ Link an existing light group to this data-block """
    bl_label = "Link Existing Light Group"
    bl_idname = 'light_groups.link'
    bl_property = "name"

    name: EnumProperty(items=lambda scn, ctx: [(x, x, x) for x in get_name_set() if x not in get_groups(ctx.object).groups])

    def invoke(self, context: 'Context', event: 'Event'):
        context.window_manager.invoke_search_popup(self)
        return {'FINISHED'}

    def execute(self, ctx):
        lgs = get_groups(ctx.object)
        new = lgs.groups.add()
        new.name = self.name

        lgs.group_index = lgs.groups.find(new.name)

        sync_light_groups()
        return {'FINISHED'}


class MAT_OT_DeleteLightGroup(LightGroupSelectionOp):
    """ Remove this light group from all data-blocks """
    bl_label = "Delete Light Group"
    bl_idname = 'light_groups.remove'

    def invoke(self, ctx, evt):
        return ctx.window_manager.invoke_confirm(self, evt)

    def execute(self, ctx):
        lgs = get_groups(ctx.object)
        grp_name = lgs.groups[lgs.group_index].name

        for mat in bpy.data.materials:
            mat.light_groups.groups.remove(mat.light_groups.groups.find(grp_name))

        for light in bpy.data.lights:
            light.light_groups.groups.remove(light.light_groups.groups.find(grp_name))

        lgs.group_index -= 1

        sync_light_groups()
        return {'FINISHED'}


class MAT_OT_UnlinkLightGroup(LightGroupSelectionOp):
    """ Remove this light group from this data-block """
    bl_label = "Unlink Light Group"
    bl_idname = 'light_groups.unlink'

    def execute(self, ctx):
        lgs = get_groups(ctx.object)
        lgs.groups.remove(lgs.group_index)

        lgs.group_index -= 1

        sync_light_groups()
        return {'FINISHED'}


class MAT_OT_ResyncLightGroups(LightGroupOp):
    """ Ensure light group layers are up to date """
    bl_label = "Resync Light Groups"
    bl_idname = 'light_groups.resync'

    def execute(self, ctx):
        sync_light_groups()
        return {'FINISHED'}


_classes = (
    LightGroup,
    LightGroups,
    MAT_UL_LightGroupList,
    OBJ_PT_MLightGroupPanel,
    OBJ_PT_LLightGroupPanel,
    MAT_OT_LinkLightGroup,
    MAT_OT_NewLightGroup,
    MAT_OT_DeleteLightGroup,
    MAT_OT_UnlinkLightGroup,
    MAT_OT_ResyncLightGroups
)

_register, _unregister = register_classes_factory(classes=_classes)


def register():
    _register()
    Material.light_groups = PointerProperty(type=LightGroups)
    Light.light_groups = PointerProperty(type=LightGroups)

    bpy.app.handlers.render_init.append(sync_handler)
    bpy.app.handlers.load_post.append(sync_handler)
    bpy.app.handlers.depsgraph_update_post.append(sync_dg_handler)


def unregister():
    _unregister()
