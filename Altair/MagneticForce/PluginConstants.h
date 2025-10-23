#ifndef PLUGINCONSTANTS_H
#define PLUGINCONSTANTS_H

/***************************************************************************/
/* This header file contains various constants and declarations used by    */
/* V2.0.0 and later plugin contact models and external forces.             */
/* It is included automatically by any plugin interface version that       */
/* needs it.                                                               */
/***************************************************************************/

// The EXPORT_MACRO should be added to the declaration of any
// factory methods to ensure EDEM can pick the method up
#ifdef _WIN32
    #ifdef __cplusplus
        #define EXPORT_MACRO extern "C" __declspec(dllexport)
    #else
        #define EXPORT_MACRO __declspec(dllexport)
    #endif
#else
    #ifdef __cplusplus
        #define EXPORT_MACRO extern "C"
    #else
        #define EXPORT_MACRO
    #endif
#endif

#endif // PLUGINCONSTANTS_H
