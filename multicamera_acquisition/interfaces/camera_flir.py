from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
import PySpin


class FlirCamera(BaseCamera):
    def __init__(self, index=0, lock=True, **kwargs):
        """
        Parameters
        ----------
        index : int or str (default: 0)
            If an int, the index of the camera to acquire.  If a string,
            the serial number of the camera.
        lock : bool (default: True)
            If True, setting new attributes after initialization results in
            an error.
        """
        # super().__init__(**kwargs)

        super().__setattr__("camera_attributes", {})
        super().__setattr__("camera_methods", {})
        super().__setattr__("camera_node_types", {})
        super().__setattr__("initialized", False)
        super().__setattr__("lock", lock)

        self.serial_number = index

        self.system = PySpin.System.GetInstance()
        cam_list = self.system.GetCameras()

        debug: print("Found %d camera(s)" % cam_list.GetSize())

        if not cam_list.GetSize():
            raise CameraError("No cameras detected.")
        if isinstance(index, int):
            self.cam = cam_list.GetByIndex(index)
        elif isinstance(index, str):
            self.cam = cam_list.GetBySerial(index)
        cam_list.Clear()
        self.running = False

    _rw_modes = {
        PySpin.RO: "read only",
        PySpin.RW: "read/write",
        PySpin.WO: "write only",
        PySpin.NA: "not available",
    }

    _attr_types = {
        PySpin.intfIFloat: PySpin.CFloatPtr,
        PySpin.intfIBoolean: PySpin.CBooleanPtr,
        PySpin.intfIInteger: PySpin.CIntegerPtr,
        PySpin.intfIEnumeration: PySpin.CEnumerationPtr,
        PySpin.intfIString: PySpin.CStringPtr,
    }

    _attr_type_names = {
        PySpin.intfIFloat: "float",
        PySpin.intfIBoolean: "bool",
        PySpin.intfIInteger: "int",
        PySpin.intfIEnumeration: "enum",
        PySpin.intfIString: "string",
        PySpin.intfICommand: "command",
    }

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""

        self.cam.Init()

        for node in self.cam.GetNodeMap().GetNodes():
            pit = node.GetPrincipalInterfaceType()
            name = node.GetName()
            self.camera_node_types[name] = self._attr_type_names.get(pit, pit)
            if pit == PySpin.intfICommand:
                self.camera_methods[name] = PySpin.CCommandPtr(node)
            if pit in self._attr_types:
                self.camera_attributes[name] = self._attr_types[pit](node)

        self.initialized = True

    def start(self):
        "Start recording images."
        if not self.running:
            self.cam.BeginAcquisition()
            self.running = True

    def stop(self):
        "Stop recording images."
        if self.running:
            self.cam.EndAcquisition()
        self.running = False

    def get_image(self, timeout=None):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        Returns
        -------
        img : PySpin Image
        """
        return self.cam.GetNextImage(
            timeout if timeout else PySpin.EVENT_TIMEOUT_INFINITE
        )

    def get_array(self, timeout=None, get_timestamp=False):
        """Get an image from the camera, and convert it to a numpy array.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        get_timestamp : bool (default: False)
            If True, returns timestamp of frame f(camera timestamp)
        Returns
        -------
        img : Numpy array
        tstamp : int
        """
        img = self.get_image(timeout)

        if not img.IsIncomplete():
            img_array = img.GetNDArray()

            if get_timestamp:
                tstamp = img.GetTimeStamp()
            else:
                tstamp = None
        else:
            img_array = None
            tstamp = None

        img.Release()

        if get_timestamp:
            return img_array, tstamp
        else:
            return img_array

    def __getattr__(self, attr):
        """Get the value of a camera attribute or method."""
        if attr in self.camera_attributes:

            prop = self.camera_attributes[attr]
            if not PySpin.IsReadable(prop):
                raise CameraError("Camera property '%s' is not readable" % attr)

            if hasattr(prop, "GetValue"):
                return prop.GetValue()
            elif hasattr(prop, "ToString"):
                return prop.ToString()
            else:
                raise CameraError("Camera property '%s' is not readable" % attr)
        elif attr in self.camera_methods:
            return self.camera_methods[attr].Execute
        else:
            raise AttributeError(attr)

    def __setattr__(self, attr, val):
        """Set the value of a camera attribute."""
        if attr in self.camera_attributes:

            prop = self.camera_attributes[attr]
            if not PySpin.IsWritable(prop):
                raise CameraError("Property '%s' is not currently writable!" % attr)

            if hasattr(prop, "SetValue"):
                prop.SetValue(val)
            else:
                prop.FromString(val)

        elif attr in self.camera_methods:
            raise CameraError(
                "Camera method '%s' is a function -- you can't assign it a value!"
                % attr
            )
        else:
            if attr not in self.__dict__ and self.lock and self.initialized:
                raise CameraError("Unknown property '%s'." % attr)
            else:
                super().__setattr__(attr, val)

    def get_info(self, name):
        """Gen information on a camera node (attribute or method).
        Parameters
        ----------
        name : string
            The name of the desired node
        Returns
        -------
        info : dict
            A dictionary of retrieved properties.  *Possible* keys include:
                - `'access'`: read/write access of node.
                - `'description'`: description of node.
                - `'value'`: the current value.
                - `'unit'`: the unit of the value (as a string).
                - `'min'` and `'max'`: the min/max value.
        """
        info = {"name": name}

        if name in self.camera_attributes:
            node = self.camera_attributes[name]
        elif name in self.camera_methods:
            node = self.camera_methods[name]
        else:
            raise ValueError("'%s' is not a camera method or attribute" % name)

        info["type"] = self.camera_node_types[name]

        if hasattr(node, "GetAccessMode"):
            access = node.GetAccessMode()
            info["access"] = self._rw_modes.get(access, access)
            # print(info['access'])
            if isinstance(info["access"], str) and "read" in info["access"]:
                info["value"] = getattr(self, name)

        # print(info)
        if info.get("access") != 0:
            for attr in ("description", "unit", "min", "max"):
                fname = "Get" + attr.capitalize()
                f = getattr(node, fname, None)
                if f:
                    info[attr] = f()
            if hasattr(node, "GetEntries"):
                entries = []
                entry_desc = []
                has_desc = False
                for entry in node.GetEntries():
                    entries.append(entry.GetName().split("_")[-1])
                    entry_desc.append(entry.GetDescription().strip())
                    if entry_desc[-1]:
                        has_desc = True
                info["entries"] = entries
                if has_desc:
                    info["entry_descriptions"] = entry_desc

        return info

    def document(self):
        """Creates a MarkDown documentation string for the camera."""
        lines = [self.DeviceVendorName.strip() + " " + self.DeviceModelName.strip()]
        lines.append("=" * len(lines[-1]))
        lines.append("")
        lines.append("*Version: %s*" % getattr(self, "DeviceVersion", "?"))
        lines.append("")

        lines.append("Attributes")
        lines.append("-" * len(lines[-1]))
        lines.append("")

        for attr in sorted(self.camera_attributes.keys()):
            if "_" in attr:
                continue
            # print(attr)
            info = self.get_info(attr)
            if not info.get("access", 0):
                continue
            lines.append("`%s` : `%s`  " % (attr, info.get("type", "?")))
            lines.append("  " + info.get("description", "(no description provided)"))
            lines.append("  - default access: %s" % info.get("access", "?"))
            if "value" in info:
                lines.append("  - default value: `%s`" % repr(info["value"]))
            if "unit" in info and info["unit"].strip():
                lines.append("  - unit: %s" % info["unit"])
            if "min" in info and "max" in info:
                lines.append("  - default range: %s - %s" % (info["min"], info["max"]))
            if "entries" in info:
                if "entry_descriptions" in info:
                    lines.append("  - possible values:")
                    for e, ed in zip(info["entries"], info["entry_descriptions"]):
                        if ed:
                            lines.append("    - `'%s'`: %s" % (e, ed))
                        else:
                            lines.append("    - `'%s'`" % e)
                else:
                    lines.append(
                        "  - possible values: %s"
                        % (", ".join("`'%s'`" % e for e in info["entries"]))
                    )

            lines.append("")

        lines.append("Commands")
        lines.append("-" * len(lines[-1]))
        lines.append("")
        lines.append(
            "**Note: the camera recording should be started/stopped using the `start` and `stop` methods, not any of the functions below (see simple_pyspin documentation).**"
        )
        lines.append("")

        for attr in sorted(self.camera_methods.keys()):
            if "_" in attr:
                continue
            # print(attr)
            info = self.get_info(attr)
            lines.append("`%s()`:  " % (attr))
            lines.append("  " + info.get("description", "(no description provided)"))
            lines.append("  - default access: %s" % info.get("access", "?"))
            lines.append("")

        return "\n".join(lines)
