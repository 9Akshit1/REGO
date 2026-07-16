#ifndef IPLUGINPARTICLEBODYFORCEV3_9_0_H
#define IPLUGINPARTICLEBODYFORCEV3_9_0_H

/***************************************************************************/
/* This header file contains the V3.9.0 plugin particle body force API     */
/* definition.  Include this header and PluginParticleBodyForceCore.h into */
/* your plugin project then implement the methods from                     */
/* PluginParticleBodyForceCore.h and create a new class derived from       */
/* IPluginParticleBodyForceV3_9_0 that implements your desired             */
/* functionality.                                                          */
/***************************************************************************/

// Include ALL required headers.  Do not use forward declarations, this
// makes things easier on the end user
#include "ICustomPropertyDataApi_1_0.h"
#include "IApiManager_1_0.h"    // AKSHIT'S CHANGE: Made the 2 to a 0
#include "IPluginParticleBodyForce.h"
#include "NExternalForceTypesV3_8_0.h"
#include "PluginConstants.h"

namespace NApiPbf
{
    namespace NApiHelpers = NApiHelpersV3_8_0;
    namespace NExternalForceTypes = NExternalForceTypesV3_8_0;

    /**
     * This interface contains all of the methods required to create a
     * particle body force plugin.  A new class should be created that
     * derives from this interface and implements all of its methods.
     * Additionally the methods from the PluginParticleBodyForceCore.h file
     * need to be implemented.
     *
     * NAME:              Particle Body Force Plugin API
     * VERSION:           3.9.0
     * CUSTOM PROPERTIES: Contact, Geometry, Particle, Simulation
     *
     * REQUIRED interface methods:
     *
     * externalForce()
     * 
     * Any other function can be over-ridden to change its behaviour.
     *
     * If you need per plugin instance data simply add entries to your
     * plugin's class definition as you would with any other C++ class
     * definition.
     */
    class IPluginParticleBodyForceV3_9_0 : public IPluginParticleBodyForce
    {
    public:
        /** API body force feature options that can be enabled during the setup call */
        enum class EApiBodyForceFeatureFlags : unsigned int
        {
            /**
            * Enable If the plugin implementations calculateForce() method is thread safe.
            *
            * When a plug-in is thread safe, EDEM allows multiple threads
            * to call the plug-in at the same time.  This can speed-up
            * calculations substantially on multi-processor machines.
            *
            * Thread safe programming requires a number of conventions and
            * restrictions to be followed.  If in doubt set this method to return
            * false.
            *
            * No effect on CUDA solvers
            *
            * Default: Indicates the plugin is not thread safe.
            */
            isThreadSafe = 0,

            /**
            * Indicates whether the plugin wants to register or receive custom property data.
            *
            * Default: Indicates the plugin does not use custom properties.
            */
            usesCustomProperties = 1,

            /**
            * Indicates whether the plugin will get the GPU source code from the library instead of the .cu file
            *
            * Default: Indicates the plugin will get the Cuda source code from .cu file
            */
            libraryProvidesGpuSource = 2,

            /**
            * Indicates whether the plugin supports custom dialog settings from UI
            *
            * Default: Indicates the plugin will not support the UI settings dialog
            */
            pluginGUIEnabled = 3,

            /**
            * Indicates whether the plugin wishes to use the particle of interest feature and call processParticleOfInterest()
            *
            * Default: Indicates the plugin will not use particle of interest.
            */
            particleOfInterest = 4
        };

        /**
         * Constructor, does nothing
         */
        IPluginParticleBodyForceV3_9_0() {}

        /**
         * Destructor, does nothing
         */
        virtual ~IPluginParticleBodyForceV3_9_0() {}

        /**
         * Retrieves the name of the config file used by the plugin.
         *
         * If the plugin does not need a config file then prefFileName
         * should be set to the empty string.
         *
         * Default: Indicates that no preference file is used.
         *
         * @param prefFileName (RETURN VALUE)
         *                     A character array to be populated with the
         *                     config file name. This path is relative to
         *                     the directory the plugin is stored in.
         *                     EDEM will prepend the full directory the plugin
         *                     is stored in and pass it back to the setup method.
         */
        virtual void getPreferenceFileName(char prefFileName[NApi::FILE_PATH_MAX_LENGTH]) {prefFileName[0] = '\0';}

        /**
         * Allows user to setup plugin parameter values. They can be modified from UI
         */
        virtual void setApiParametersTemplate() const { }

        /**
         * Initializes the plugin by giving it the path to the simulation files.
         *
         * This method is called once, shortly after the plugin is first loaded,
         * within the call to function starting(...).
         *
         * IMPORTANT: Plugins should not cache API handles in this
         * method.  See the starting(...) and stopping(...) methods.
         *
         * @param simFile Full path to simulation file or empty
         *                 string if none
         * @return void
         */
        virtual void setFilePath(const char simFile[]) {;}

        /**
         * Initializes GPU plugin by accepting its file name without extension.
         *
         * Default: Does nothing.
         *
         * If empty, the model will not be supported on the GPU solver.
         * @param nameFile the name of the cu file. Do not include the extension .cu
         */
        virtual void getGpuFileName(char nameFile[NApi::FILE_PATH_MAX_LENGTH]) {;}

        /**
         * User needs to set the size of the char array, which contains the cuda source code
         * If libraryProvidesGpuSource() is true. 
         *
         * For example getGpuSourceSize() function could return
         * static_cast<unsigned int>(GPU_CODE.size()); where GPU_CODE is defined as
         * std::string GPU_CODE = R"( GPU code )";
         *
         * Default: 0
         *
         * @return the actual size of the char array
         */
        virtual unsigned int getGpuSourceSize() { return 0; }

        /**
         * User needs to set the char array with the cuda source code,
         * If libraryProvidesGpuSource() is true
         *
         * @param the cuda source code in char array
         */
        virtual void getGpuSource(char gpuCode[]) { ; }

        /**
         * Initializes the plugin by giving it a chance to read any config
         * files, open temporary files, generate data structures or any other
         * one-off setup work.
         *
         * This method is called once, shortly after the plugin is first loaded.
         * If this method returns false EDEM will immediately delete the plugin
         * and an error message will be reported.
         *
         * IMPORTANT: Plugins should not cache API handles in this
         * method.  See the starting(...) and stopping(...) methods.
         *
         * Default: Performs no work but returns true to indicate plugin loaded cleanly.
         *
         * @param  featureFlags       Features that this api physics model supports, to be set by the user.
         *                            see enum class EApiBodyForceFeatureFlags for more details in the ApiTypes.h header.
         * @param  solverFlags        Defines which solver engine this plugin supports.
         * @param  particleShapeFlags Defines which particle shapes this plugin supports.
         * @param  physicsModelName   Defines the name of the physics model.
         * @param  prefFile           Full path to optional preferences file or empty
         *                            string if none.
         * @param  customMsg          (RETURN VALUE)
         *                            Character buffer to pass a custom error message to EDEM.
         * @return bool               To say if setup was a success.
         */
        virtual bool setup(NApiHelpers::CFlags<EApiBodyForceFeatureFlags>& featureFlags,
                           NApiHelpers::CFlags<NApi::EApiSolverFlags>& solverFlags,
                           NApiHelpers::CFlags<NApi::EApiParticleShapeFlags>& particleShapeFlags,
                           NApiHelpers::CSimpleString& physicsModelName,
                           const char prefFile[],
                           char customMsg[NApi::ERROR_MSG_MAX_LENGTH]) = 0;

        /**
         * Called to indicate processing is about to begin and the
         * model should allocate any temporary storage and retrieve any
         * file/API/socket handles it may need
         *
         * If the method returns false then processing will not start.
         *
         * IMPORTANT: Plugins should only retrieve API handles in this
         * method. API handles may change between one processing
         * run and another. Attempting to keep and re-use handles
         * will cause system instability.
         *
         * Default: Performs no work but returns true to indicate plugin
         *          is ready to start processing.
         *
         * @param numThreads The number of threads this will be run with.
         * @param associatedFile Location of files related to this plugins operation (GUI Values file, or prefFile if unused, or empty if both unused).
         * @return true if model is ready to start, else false
         */
        virtual bool starting(int numThreads,
                              char guiPath[NApi::GUI_FILE_MAX_LENGTH])
        {
            return true;
        }

        /**
         * Called once at the end of a simulation to indicate processing is finished.
         *
         * The implementation must be able to handle this method being called multiple
         * times in a row without intervening calls to starting. This can occur when one
         * or more loaded models abort processing.
         *
         * Default: Does nothing
         */
        virtual void stopping() {}

        /**
         * Use externalForce to add particle body forces (such as
         * electromagnetic or drag forces) to particles. This function
         * is called every single time step for every single particle.
         * 
         * When using the CUDA solvers this will have no effect but an empty implementation must still be provided.
         * In this case the particle body force calculation only needs to be implemented in the CUDA .cu file.
         * However, when using CPU solver this will have to be implemented or forces will be ignored.
         *
         * @param threadID                      The ID of the thread, in which this method is running,
         *                                      if multi-threaded (isThreadSafe must return true).
         * @param timeStepData                  Stores this time step's current time and the length of this time step.
         * @param particle                      Particle element, see NExternalForceTypes::SParticle for further details.
         * @param particleCustomProperties      Versioned interface providing access to the particle's
         *                                      custom property data and corresponding changeset.
         * @param simulationCustomProperties    Versioned interface providing access to custom
         *                                      property data and corresponding changeset for the simulation.
         * @param results                       (RETURN VALUE), see NExternalForceTypes::SResults for further details.
         * @return enum                         Value to indicate function result.
         */
        virtual NApi::ECalculateResult externalForce(int threadID,
                                                     const NExternalForceTypes::STimeStepData& timeStepData,
                                                     const NExternalForceTypes::SParticle& particle,
                                                     NApiCore::ICustomPropertyDataApi_1_0* particleCustomProperties,
                                                     NApiCore::ICustomPropertyDataApi_1_0* simulationCustomProperties,
                                                     NExternalForceTypes::SResults& results) = 0;

        /**
         * Returns the number of custom properties this plugin wants to
         * register with the system for the supplied category.
         *
         * This version of the API supports the following property
         * categories:
         *     Contact Properties
         *     Geometry Properties
         *     Particle Properties
         *     Simulation Properties
         *
         * The method will be called once for each category at load time.
         * The implementation should return how many properties of that
         * category it wishes to register.
         *
         * If the plugin does not use custom properties this method should
         * return 0 for all categories.
         *
         * Default: Returns 0 to indicate no properties are required for any category.
         *
         * @param category The category of the custom property.
         * @return The number of custom properties the plugin wishes to
         *         register.
         */
        virtual unsigned int getNumberOfRequiredProperties(const NApi::EPluginPropertyCategory category) {return 0;}

        /**
         * Retrieves details for a given property.  This method will be
         * called for each category for propertyIndex values
         * 0...(getNumberOfRequiredProperties(category) - 1) to retrieve
         * the details for that property from the plugin.  These properties
         * will then be registered with the system if they do not clash
         * with any existing properties.
         *
         * This version of the API supports the following property
         * categories:
         *     Contact Properties
         *     Geometry Properties
         *     Particle Properties
         *     Simulation Properties
         *
         * If the plugin does not use custom properties this method should
         * always return false.
         *
         * Default: Returns false.
         *
         * @param propertyIndex    The index of the property to retrieve data
         *                         for
         * @param category         The category of the custom property to return
         *                         details for.
         * @param name             (RETURN VALUE)
         *                         A CUSTOM_PROP_MAX_NAME_LENGTH char array
         *                         is supplied to be populated with the name
         *                         of the property
         * @param dataType         (RETURN VALUE)
         *                         The data type of the property should always
         *                         be set to eDouble
         * @param numberOfElements (RETURN VALUE)
         *                         The number of elements (min 1)
         * @param unitType         (RETURN VALUE)
         *                         The unit type of the property
         * @param initValBuff      (RETURN VALUE)
         *                         Delimited string with details of the initial values
         *                         for each of the properties elements
         *
         * @return bool to say if data exists for the property
         */
        virtual bool getDetailsForProperty(unsigned int propertyIndex,
                                           NApi::EPluginPropertyCategory category,
                                           char name[NApi::CUSTOM_PROP_MAX_NAME_LENGTH],
                                           NApi::EPluginPropertyDataTypes& dataType,
                                           unsigned int& numberOfElements,
                                           NApi::EPluginPropertyUnitTypes& unitType,
                                           char initValBuff[NApi::BUFF_SIZE]) {return false;}

        /**
         * Enables custom functionality to be carried out on a per timestep basis.
         * The function is called at the start of each timestep to enable per timestep
         * configuration to be carried out
         *
         * If the plugin does not use custom properties this method should
         * return 0 for all categories.
         * 
         * Should be empty for CUDA solvers. Should be implemented only on CUDA file.
         *
         * Default: Does nothing.
         *
         * @param simData Details of the associated simulation property details
         * @param time The current simulation time
         */
        virtual void configForTimeStep(NApiCore::ICustomPropertyDataApi_1_0* simData,
                                       double time)
        {}
        
        /**
         * Gets the particle parameter data in a buffer format
         *
         * Default: Returns 0.
         *
         * @param particleType The name/type of the particle
         * @param parameterData A preallocated buffer of size PARAM_MAX_SIZE containing parameter values for the particle type
         * @return The actual size of the parameter data
         */
        virtual unsigned int getParticleParameterData(const char particleType[], void* parameterData) {return 0;}

        /**
         * Gets the simulation parameter data in a buffer format
         *
         * Default: Returns 0.
         *
         * @param parameterData A preallocated buffer of size PARAM_MAX_SIZE containing simulation parameter values
         * @return The actual size of the parameter data
         */
        virtual unsigned int getSimulationParameterData(void* parameterData) {return 0;}

        /**
         * Process particles that were marked for additional processing in externalForce call.
         * Particle modifications are not allowed.
         *
         * Default: Does nothing
         *
         * @param threadID The ID of the thread, in which this method is running,
                           if multi-threaded (isThreadSafe must return true).
         * @param particleOfInterestId One of the particle IDs that requires additional processing.
         */
        virtual void processParticleOfInterest(int threadID, int particleOfInterestId) {}

        /** @return the API manager. Users can implement similar functions for any api manager version */
        NApiCore::IApiManager_1_2* getApiManager() const { return static_cast<NApiCore::IApiManager_1_2*>(apiManager); }

        /**
         * This is called once during the loading of the API to set the apiManager.
         */
        void setApiManager(NApiCore::IApi* api) { apiManager = api; }

    private:
        NApiCore::IApi* apiManager = nullptr;
    };
};

#endif 
