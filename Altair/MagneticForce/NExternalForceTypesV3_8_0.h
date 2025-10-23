#ifndef NEXTERNALFORCETYPESV3_8_0_H
#define NEXTERNALFORCETYPESV3_8_0_H

#include "HelpersV3_8_0.h"
#include "NExternalForceTypesV3_4_0.h"

namespace NExternalForceTypesV3_8_0
{
    namespace NApiHelpers = NApiHelpersV3_8_0;
    namespace NExternalForceTypes = NExternalForceTypesV3_4_0;

    /**
     * This struct represents particle element, which is used to modify particle body forces (such as electromagnetic or drag forces).
     */
    struct SParticle
    {
        int ID;           /**< The id of the particle. */
        unsigned int typeIndex; /** particle type index */

        unsigned int NumOfSpheres;                 /**< The number of spheres of the particle. */
        double mass;                               /**< The mass of the particle. */
        double volume;                             /**< The volume of the particle. */
        double density;                            /**< The density of the particle. */

        double scale;                              /**< The scale of the particle. */

        NApiHelpers::CSimple3DVector position;     /**< The centroid of the particle. */
        NApiHelpers::CSimple3DVector velocity;     /**< The velocity the particle. */
        NApiHelpers::CSimple3DVector angVel;       /**< The angular velocity of the particle. */
        NApiHelpers::CSimple3DVector moi;          /**< The moment of inertia of the particle. */
        NApiHelpers::CSimple3x3Matrix orientation; /**< Nine element array containing the orientation matrix for this particle. The elements of the array are in the following order: XX, XY, XZ, YX, YY, YZ, ZX, ZY, ZZ.*/

        const char* type; /**< Name of the particle template, from which this particle was created. */
    };

    /** Return values. */
    using NExternalForceTypes::SResults;

    /** Stores a time step's current time and the length of the time step.*/
    using NExternalForceTypes::STimeStepData;
}

#endif // NEXTERNALFORCETYPESV3_8_0_H
