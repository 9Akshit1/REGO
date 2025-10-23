// ===========================================================================
// MagneticForceCore.cpp - Plugin Core File
// Required implementations for EDEM API plugin loading
// ===========================================================================

#include "PluginParticleBodyForceCore.h"
#include "MagneticForce.h"

// Export macro for getting interface version
EXPORT_MACRO int GETPBFINTERFACEVERSION()
{
    static const int INTERFACE_VERSION_MAJOR = 0x03;
    static const int INTERFACE_VERSION_MINOR = 0x09;
    static const int INTERFACE_VERSION_PATCH = 0x00;
    return (INTERFACE_VERSION_MAJOR << 16 |
            INTERFACE_VERSION_MINOR << 8 |
            INTERFACE_VERSION_PATCH);
}

// Export macro for creating plugin instance
EXPORT_MACRO IPluginParticleBodyForce* CREATEPBFPLUGININSTANCE()
{
    return new CMagneticForce();
}

// Export macro for destroying plugin instance
EXPORT_MACRO void DESTROYPBFPLUGININSTANCE(IPluginParticleBodyForce* pInstance)
{
    delete pInstance;
}