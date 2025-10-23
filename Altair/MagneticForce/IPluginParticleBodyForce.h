#ifndef IPLUGINPARTICLEBODYFORCE_H
#define IPLUGINPARTICLEBODYFORCE_H

/**
 * The NApiPbf namespace contains all interfaces related
 * to creating Particle Body Force plugins.
 *
 * Pick one of the versioned interfaces (e.g. IPluginParticleBodyForceV2_0_0)
 * and implement all of its methods as required.  Also implement the
 * methods declared in PluginParticleBodyForceCore.h to enable EDEM to load
 * and access the plugin instance.
 */
namespace NApiPbf
{
    /**
     * Base class for all plugin particle body forces.  This class
     * lets us abstractly group all plugin particle body forces together
     * and determine their type by dynamic_cast operators.
     */
    class IPluginParticleBodyForce
    {
    public:
        /**
         * Constructor, does nothing
         */
        IPluginParticleBodyForce() {}

        /**
         * Destructor, does nothing
         */
        virtual ~IPluginParticleBodyForce() {}
    };
};

#endif // IPLUGINPARTICLEBODYFORCE_H

